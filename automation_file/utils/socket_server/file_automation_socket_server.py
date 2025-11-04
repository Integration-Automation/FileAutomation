import json
import socketserver
import sys
import threading

from automation_file.utils.executor.action_executor import execute_action


class TCPServerHandler(socketserver.BaseRequestHandler):
    """
    TCPServerHandler 負責處理每個 client 的請求
    TCPServerHandler handles each client request
    """

    def handle(self):
        # 接收 client 傳來的資料 (最大 8192 bytes)
        # Receive data from client
        command_string = str(self.request.recv(8192).strip(), encoding="utf-8")
        socket = self.request
        print("command is: " + command_string, flush=True)

        # 若收到 quit_server 指令，則關閉伺服器
        # Shutdown server if quit_server command received
        if command_string == "quit_server":
            self.server.shutdown()
            self.server.close_flag = True
            print("Now quit server", flush=True)
        else:
            try:
                # 將接收到的 JSON 字串轉換為 Python 物件
                # Parse JSON string into Python object
                execute_str = json.loads(command_string)

                # 執行對應的動作，並將結果逐一回傳給 client
                # Execute actions and send results back to client
                for execute_function, execute_return in execute_action(execute_str).items():
                    socket.sendto(str(execute_return).encode("utf-8"), self.client_address)
                    socket.sendto("\n".encode("utf-8"), self.client_address)

                # 傳送結束標記，讓 client 知道資料已傳完
                # Send end marker to indicate data transmission is complete
                socket.sendto("Return_Data_Over_JE".encode("utf-8"), self.client_address)
                socket.sendto("\n".encode("utf-8"), self.client_address)

            except Exception as error:
                # 錯誤處理：將錯誤訊息輸出到 stderr 並回傳給 client
                # Error handling: log to stderr and send back to client
                print(repr(error), file=sys.stderr)
                try:
                    socket.sendto(str(error).encode("utf-8"), self.client_address)
                    socket.sendto("\n".encode("utf-8"), self.client_address)
                    socket.sendto("Return_Data_Over_JE".encode("utf-8"), self.client_address)
                    socket.sendto("\n".encode("utf-8"), self.client_address)
                except Exception as error:
                    print(repr(error))


class TCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """
    自訂 TCPServer，支援多執行緒處理
    Custom TCPServer with threading support
    """

    def __init__(self, server_address, request_handler_class):
        super().__init__(server_address, request_handler_class)
        self.close_flag: bool = False


def start_autocontrol_socket_server(host: str = "localhost", port: int = 9943):
    """
    啟動自動控制 TCP Socket Server
    Start the auto-control TCP Socket Server

    :param host: 主機位址 (預設 localhost)
                 Host address (default: localhost)
    :param port: 監聽埠號 (預設 9943)
                 Port number (default: 9943)
    :return: server instance
    """
    # 支援從命令列參數指定 host 與 port
    # Support overriding host and port from command line arguments
    if len(sys.argv) == 2:
        host = sys.argv[1]
    elif len(sys.argv) == 3:
        host = sys.argv[1]
        port = int(sys.argv[2])

    server = TCPServer((host, port), TCPServerHandler)

    # 使用背景執行緒啟動 server
    # Start server in a background thread
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    return server