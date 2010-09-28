#!/usr/bin/env python
import os
import sys
import time
import string
import socket
import shutil
import subprocess
from optparse import OptionParser

class MathMate(object):
    def __init__(self):
        self.cacheFolder = '/tmp/tmjlink'
        self.mlargs = ["-linkmode", "launch", "-linkname", "/Applications/Mathematica.app/Contents/MacOS/MathKernel", "-mathlink"]
        
        self.parse_tree_level = None
        self.doc = sys.stdin.read()
        
        self.indent_size = int(os.environ['TM_TAB_SIZE'])
        if os.environ.get('TM_SOFT_TABS') == "YES":
            self.indent = " " * self.indent_size
        elif os.environ.get('TM_SOFT_TABS') == "NO":
            self.indent = "\t"
        
        self.tmln = int(os.environ.get('TM_LINE_NUMBER'))
        self.tmli = int(os.environ.get('TM_LINE_INDEX'))
        self.tmcursor = self.get_pos(self.tmln, self.tmli)
        self.selected_text = os.environ.get('TM_SELECTED_TEXT')
        self.statements = self.parse(self.doc)
        
        sessid = os.path.split(os.environ.get('TM_FILEPATH', 'mathmate-default'))[-1]
        if sessid.endswith(".m"):
            self.sessid = sessid[:-2]
        else:
            self.sessid = sessid
    
    def shutdown(self):
        pidfile = os.path.join(self.cacheFolder, "tmjlink.pid")
        if os.path.exists(pidfile):
            try:
                pidfp = open(pidfile, 'r')
                pid = int(pidfp.read())
                pidfp.close()
                os.kill(pid, 1)
                print "TextMateJLink Server Shutdown"
                return
            except:
                pass
        print "TextMateJLink Server is not Running"
    
    def is_tmjlink_alive(self):
        pidfile = os.path.join(self.cacheFolder, "tmjlink.pid")
        if os.path.exists(pidfile):
            try:
                pidfp = open(pidfile, 'r')
                pid = int(pidfp.read())
                pidfp.close()
                
                os.kill(pid, 0)
                return True
            except:
                pass
        return False
    
    def launch_tmjlink(self):
        if self.is_tmjlink_alive():
            return
        
        classpath = []
        classpath.append(os.path.join(os.environ.get('TM_BUNDLE_SUPPORT'), "tmjlink"))
        classpath.append("/Applications/Mathematica.app/SystemFiles/Links/JLink/JLink.jar")
        
        if os.path.exists(self.cacheFolder):
           shutil.rmtree(self.cacheFolder) 
        os.mkdir(self.cacheFolder, 0777)
        for sfile in ("jquery-1.4.2.min.js", "layout.html.erb", "tmjlink.css", "header_bg.gif"):
            os.symlink(os.path.join(os.environ.get('TM_BUNDLE_SUPPORT'), "web", sfile), os.path.join(self.cacheFolder, sfile))
        
        # Launch TextMateJLink
        logfp = open(os.path.join(self.cacheFolder, "tmjlink.log"), 'w')
        proc = subprocess.Popen(['/usr/bin/java', 
                '-cp', ":".join(classpath), 
                'com.shadanan.textmatejlink.TextMateJLink', 
                self.cacheFolder, str(os.getppid())] + self.mlargs,
            stdout=logfp, stderr=subprocess.STDOUT)
        logfp.close()
        
        # Save PID file
        pidfp = open(os.path.join(self.cacheFolder, "tmjlink.pid"), 'w')
        pidfp.write(str(proc.pid))
        pidfp.close()
        
    def readline(self, sock):
        result = []
        while True:
            char = sock.recv(1)
            
            if char == "\r":
                continue
                
            if char == "\n":
                break
                
            if char == "":
                return None
                
            result.append(char)
            
        return "".join(result)
    
    def connect(self):
        self.launch_tmjlink()
        
        # Wait for server to be ready and get listen port
        logfp = open(os.path.join(self.cacheFolder, "tmjlink.log"), 'r')
        while True:
            line = logfp.readline()
            if line == "":
                time.sleep(0.1)
                continue
            if line.strip().startswith("Server started on port: "):
                port = int(line.strip()[24:])
                break
        logfp.close()
    
        sock = socket.socket()
        sock.connect(("localhost", port))
        return sock
    
    def read(self, sock):
        line = self.readline(sock)

        if line is None:
            raise Exception("The server quit unexpectedly.")
            
        if line.find(" -- ") != -1:
            response = line[0:line.find(" -- ")]
            comment = line[line.find(" -- ")+4:]
        else:
            response = line
            comment = None
            
        words = response.split(" ")
        return (line, response, words, comment)
    
    def execute(self, force_image = False):
        sock = self.connect()
        
        statements = []
        if self.selected_text is not None:
            for ssp, esp, reformatted_statement, current_statement in self.statements:
                statements.append(current_statement)
        else:
            ssp, esp, reformatted_statement, current_statement = self.get_current_statement()
            statements.append(current_statement)
        
        state = 0
        while True:
            line, response, words, comment = self.read(sock)
            
            if state == 0:
                if response == "TMJLink Status OK":
                    sock.send("sessid %s\n" % self.sessid)
                    state = 1
                    continue
            
                if response == "TMJLink Exception":
                    raise Exception("TextMateJLink Exception: " + comment)

                raise Exception("Unexpected message from JLink server: " + line)
                
            if state == 1:
                if response == "TMJLink Okay":
                    statement = statements.pop(0).rstrip()
                    if force_image:
                        sock.send("evali %d\n" % len(statement))
                    else:
                        sock.send("eval %d\n" % len(statement))
                    sock.send(statement)
                    
                    if len(statements) == 0:
                        state = 2
                        
                    continue
                        
                if response == "TMJLink Exception":
                    raise Exception("TextMateJLink Exception: " + comment)

                raise Exception("Unexpected message from JLink server: " + line)
            
            if state == 2:
                if response == "TMJLink Okay":
                    sock.send("show\n")
                    state = 3
                    continue
            
                if response == "TMJLink Exception":
                    raise Exception("TextMateJLink Exception: " + comment)

                raise Exception("Unexpected message from JLink server: " + line)
                
            if state == 3:
                if words[0] == "TMJLink" and words[1] == "FileSaved":
                    output_html = words[2]
                    sock.send("quit\n")
                    state = 4
                    continue
                
                if response == "TMJLink Exception":
                    raise Exception("TextMateJLink Exception: " + comment)

                raise Exception("Unexpected message from JLink server: " + line)
            
            if state == 4:
                if response == "TMJLink Okay":
                    sock.close()
                    break
            
                if response == "TMJLink Exception":
                    raise Exception("TextMateJLink Exception: " + comment)

                raise Exception("Unexpected message from JLink server: " + line)
            
            raise Exception("Invalid state: " + state)
        
        print "<meta http-equiv='Refresh' content='0;URL=file://%s'>" % output_html
    
    def clear(self):
        sock = self.connect()
        
        state = 0
        while True:
            line, response, words, comment = self.read(sock)
            
            if state == 0:
                if response == "TMJLink Status OK":
                    sock.send("sessid %s\n" % self.sessid)
                    state = 1
                    continue
            
                if response == "TMJLink Exception":
                    raise Exception("TextMateJLink Exception: " + comment)

                raise Exception("Unexpected message from JLink server: " + line)
                
            if state == 1:
                if response == "TMJLink Okay":
                    sock.send("clear\n")
                    state = 2
                    continue
                        
                if response == "TMJLink Exception":
                    raise Exception("TextMateJLink Exception: " + comment)

                raise Exception("Unexpected message from JLink server: " + line)
            
            if state == 2:
                if response == "TMJLink Okay":
                    sock.send("quit\n")
                    state = 3
                    continue
            
                if response == "TMJLink Exception":
                    raise Exception("TextMateJLink Exception: " + comment)

                raise Exception("Unexpected message from JLink server: " + line)
                
            if state == 3:
                if response == "TMJLink Okay":
                    sock.close()
                    break
            
                if response == "TMJLink Exception":
                    raise Exception("TextMateJLink Exception: " + comment)

                raise Exception("Unexpected message from JLink server: " + line)
            
            raise Exception("Invalid state: " + state)
        
        print "Session Cleared"
            
    def reset(self):
        sock = self.connect()

        state = 0
        while True:
            line, response, words, comment = self.read(sock)

            if state == 0:
                if response == "TMJLink Status OK":
                    sock.send("sessid %s\n" % self.sessid)
                    state = 1
                    continue

                if response == "TMJLink Exception":
                    raise Exception("TextMateJLink Exception: " + comment)

                raise Exception("Unexpected message from JLink server: " + line)

            if state == 1:
                if response == "TMJLink Okay":
                    sock.send("reset\n")
                    state = 2
                    continue

                if response == "TMJLink Exception":
                    raise Exception("TextMateJLink Exception: " + comment)

                raise Exception("Unexpected message from JLink server: " + line)

            if state == 2:
                if response == "TMJLink Okay":
                    sock.send("quit\n")
                    state = 3
                    continue

                if response == "TMJLink Exception":
                    raise Exception("TextMateJLink Exception: " + comment)

                raise Exception("Unexpected message from JLink server: " + line)

            if state == 3:
                if response == "TMJLink Okay":
                    sock.close()
                    break

                if response == "TMJLink Exception":
                    raise Exception("TextMateJLink Exception: " + comment)

                raise Exception("Unexpected message from JLink server: " + line)

            raise Exception("Invalid state: " + state)

        print "Session Reset"

    def get_pos(self, line, column):
        line_index = 1
        line_pos = 0
    
        for pos, char in enumerate(self.doc):
            if line == line_index and column == pos - line_pos:
                return pos
        
            if char == "\n":
                line_index += 1
                line_pos = pos + 1
    
    def get_line_col(self, posq):
        line_index = 1
        line_pos = 0
        
        for pos, char in enumerate(self.doc):
            if posq == pos:
                return (line_index, pos - line_pos)
        
            if char == "\n":
                line_index += 1
                line_pos = pos + 1
        
        return (line_index, pos - line_pos)

    def count_indents(self, line):
        count = 0
        space_count = 0

        for char in line.rstrip():
            if char == "\t":
                count += 1
            elif char == " ":
                space_count = ((space_count + 1) % self.indent_size)
                if space_count == 0:
                    count += 1
            else:
                break
        return count
    
    def get_next_non_space_char(self, pos):
        for i in xrange(pos, len(self.doc)):
            if self.doc[i] in (" ", "\t"):
                continue
            if self.doc[i] == "\n":
                return None
            return self.doc[i]
        return None
    
    def get_prev_non_space_char(self, pos):
        for i in xrange(pos, -1, -1):
            if self.doc[i] in (" ", "\t"):
                continue
            if self.doc[i] == "\n":
                return None
            return self.doc[i]
        return None

    def is_end_of_line(self, pos):
        return self.get_next_non_space_char(pos) == None
    
    def parse(self, block, initial_indent_level = None):
        statements = []
        
        pos = 0
        ss_pos = 0
        current = []
        scope = []
        
        if initial_indent_level is None:
            initial_indent_level = self.count_indents(block)
        
        while pos < len(block):
            c1 = block[pos]
            c2 = block[pos:pos+2]
            c3 = block[pos:pos+3]
            pc = block[pos-1] if pos > 0 else None

            nnsc = None
            for i in xrange(pos + 1, len(block)):
                if block[i] == "\n":
                    break
                    
                if block[i] not in (" ", "\t"):
                    nnsc = block[i]
                    break

            if pos == self.tmcursor:
                self.parse_tree_level = ".".join(scope)

            if len(scope) == 0:
                if c1 != "\n" and nnsc is not None:
                    if current != []:
                        statements.append((ss_pos, pos, "".join(current), block[ss_pos:pos]))
                        current = []

                    ss_pos = pos
                    scope.append("root")
                    
                    indent_level = len(scope) + initial_indent_level - 1
                    if nnsc in ("]", "}", ")"):
                        current += (self.indent * (indent_level - 1))
                    else:
                        current += (self.indent * indent_level)
                    
                    while block[pos] in (" ", "\t"):
                        pos += 1
                    continue
                
                if c1 in (" ", "\t") and nnsc is not None:
                    ss_pos = pos
                    scope.append("root")
                    
                    indent_level = len(scope) + initial_indent_level - 1
                    if nnsc in ("]", "}", ")"):
                        current += (self.indent * (indent_level - 1))
                    else:
                        current += (self.indent * indent_level)
                    
                    while block[pos] in (" ", "\t"):
                        pos += 1
                    continue
                    
                current += c1
                pos += 1
                continue

            if scope[-1] == "string":
                if c2 == '\\"':
                    current += c2
                    pos += 2
                    continue

                if c1 == '"':
                    scope.pop()
                    current += c1
                    pos += 1
                    continue

                current += c1
                pos += 1
                continue

            if scope[-1] == "comment":
                if c3 == '\\*)':
                    current += c3
                    pos += 3
                    continue
                
                if c2 == '(*':
                    scope.append("comment")
                    current += c2
                    pos += 2
                    continue
                
                if c2 == '*)':
                    scope.pop()
                    current += c2
                    pos += 2
                    continue

                current += c1
                pos += 1
                continue

            if c1 in (" ", "\t"):
                vsc = string.ascii_letters + string.digits
                if pc is not None and nnsc is not None and pc in vsc and nnsc in vsc:
                    current += " "
                pos += 1
                continue
        
            if c3 in ("===", ">>>", "^:="):
                if self.is_end_of_line(pos + 3):
                    scope += ("binop", "start")
                current += " ", c3, " "
                pos += 3
                continue

            if c2 in ("*^", "&&", "||", "==", ">=", "<=", ";;", "/.", "->", ":>", "@@", "<>", ">>", "/@", "/;", "//", "~~", ":=", "^="):
                if self.is_end_of_line(pos + 2):
                    scope += ("binop", "start")
                current += " ", c2, " "
                pos += 2
                continue

            if c2 == "..":
                current += c2, " "
                pos += 2
                continue

            if c2 == "(*":
                scope.append("comment")
                current += c2
                pos += 2
                continue

            if c2 == "[[":
                scope.append("part")
                current += c2
                pos += 2
                continue
        
            if c2 == "]]" and scope[-1] == "part":
                scope.pop()
                current += c2
                pos += 2
                continue
        
            if c1 == "[":
                scope.append("function")
                current += c1
                pos += 1
                continue
        
            if c1 == "]":
                scope.pop()
                current += c1
                pos += 1
                continue
        
            if c1 == "{":
                scope.append("list")
                current += c1
                pos += 1
                continue
        
            if c1 == "}":
                if scope[-1] == "binop":
                    scope.pop()
                scope.pop()
                current += c1
                pos += 1
                continue
        
            if c1 == "(":
                scope.append("group")
                current += c1
                pos += 1
                continue
        
            if c1 == ")":
                # if scope[-1] == "binop":
                #     scope.pop()
                scope.pop()
                current += c1
                pos += 1
                continue
            
            if c1 == "!":
                current += c1, " "
                pos += 1
                continue
                
            if c1 == "?":
                current += c1
                pos += 1
                continue
            
            if c1 in ("+", "*", "/", "^", ">", "<", "|", "="):
                if self.is_end_of_line(pos + 1):
                    scope += ("binop", "start")
                current += " ", c1, " "
                pos += 1
                continue
            
            if c1 == "-":
                if self.is_end_of_line(pos + 1):
                    scope += ("binop", "start")
                    
                if self.get_prev_non_space_char(pos-1) not in (None, "{", "(", "[", ","):
                    current += " ", c1, " "
                else:
                    current += c1
                pos += 1
                continue

            if c1 == "&":
                current += " ", c1
                pos += 1
                continue
            
            if c1 == ",":
                if scope[-1] == "binop":
                    scope.pop()
                current += c1, " "
                pos += 1
                continue

            if c1 == ";":
                if scope[-1] == "binop":
                    scope.pop()
                if scope[-1] == "root":
                    scope.pop()
                current += c1
                pos += 1
                continue

            if c1 == "\n":
                if scope[-1] == "binop":
                    scope.pop()
                if scope[-1] == "start":
                    scope.pop()
                if scope[-1] == "root":
                    scope.pop()
                current += c1
                pos += 1

                indent_level = len(scope) + initial_indent_level - 1
                if nnsc in ("]", "}", ")"):
                    current += (self.indent * (indent_level - 1))
                else:
                    current += (self.indent * indent_level)

                continue
                
            if c1 == '"':
                scope.append("string")
                current += c1
                pos += 1
                continue
            
            current += c1
            pos += 1
            continue

        if current != []:
            statements.append((ss_pos, pos, "".join(current), block[ss_pos:pos]))
        return statements
    
    def get_current_statement_index(self):
        for index, (ssp, esp, reformatted_statement, current_statement) in enumerate(self.statements):
            if self.tmcursor >= ssp and self.tmcursor < esp:
                return index
        return len(self.statements) - 1
            
    def get_current_statement(self):
        return self.statements[self.get_current_statement_index()]
    
    def reformat(self):
        if self.selected_text is not None:
            for ssp, esp, reformatted_statement, current_statement in self.statements:
                sys.stdout.write(reformatted_statement)
        else:
            ssp, esp, reformatted_statement, current_statement = self.get_current_statement()
            sys.stdout.write(self.doc[0:ssp])
            sys.stdout.write(reformatted_statement)
            sys.stdout.write(self.doc[esp:])

    def show(self):
        print "Cursor: (Line: %d, Index: %d, Tree: %s)" % (self.tmln, self.tmli, self.parse_tree_level)

        if self.selected_text is None:
            ssp, esp, reformatted_statement, current_statement = self.get_current_statement()
            ssln, ssli = self.get_line_col(ssp)
            esln, esli = self.get_line_col(esp)
            print "Statement Boundaries: (Line: %d, Index: %d) -> (Line: %d, Index: %d)" % (ssln, ssli, esln, esli)
            print reformatted_statement,
        else:
            for index, (ssp, esp, reformatted_statement, current_statement) in enumerate(self.statements):
                ssln, ssli = self.get_line_col(ssp)
                esln, esli = self.get_line_col(esp)
                print "Statement %d Boundaries: (Line: %d, Index: %d) -> (Line: %d, Index: %d)" % (index, ssln, ssli, esln, esli)
                if len(reformatted_statement.strip()) != 0:
                    print reformatted_statement.rstrip()
                else:
                    print "*** Empty Statement ***"
                print

def main():
    parser = OptionParser()
    (options, args) = parser.parse_args()
    command = args[0]
    
    mm = MathMate()
    
    if command == "show":
        mm.show()
        return
    
    if command == "execute":
        mm.execute()
        return
    
    if command == "image":
        mm.execute(True)
        return
    
    if command == "clear":
        mm.clear()
        return
    
    if command == "reset":
        mm.reset()
        return
    
    if command == "shutdown":
        mm.shutdown()
        return
    
    if command == "reformat":
        mm.reformat()
        return
    
    print "Command not recognized: %s" % command

if __name__ == '__main__':
    main()