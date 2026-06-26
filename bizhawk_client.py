import socket
import threading
import json
import time
import queue
import logging

class BizhawkClient:
    """
    A robust Python library to communicate with the connector_bizhawk_generic.lua script.
    It automatically searches for the correct port, handles reconnects, and keeps the
    connection alive with PINGs.
    
    This is designed to be easily slotted into a GUI application without blocking the main loop.
    """
    def __init__(self, host='127.0.0.1', start_port=43055, end_port=43060, auto_start=True):
        self.host = host
        self.start_port = start_port
        self.end_port = end_port
        
        self._socket = None
        self._socket_file = None
        self._connected = False
        self._running = False
        self._thread = None
        
        self._send_queue = queue.Queue()
        self._callbacks = []

        if auto_start:
            self.start()

    @property
    def is_connected(self):
        """Returns True if currently connected to Bizhawk."""
        return self._connected

    def add_connection_callback(self, callback):
        """
        Register a callback function that takes a boolean `is_connected`.
        Useful for binding to a UI element to show connection status.
        """
        if callback not in self._callbacks:
            self._callbacks.append(callback)
            try:
                callback(self._connected)
            except Exception as e:
                logging.error(f"Error in connection callback: {e}")

    def remove_connection_callback(self, callback):
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _set_connected(self, state):
        if self._connected != state:
            self._connected = state
            for cb in self._callbacks:
                try:
                    cb(state)
                except Exception as e:
                    logging.error(f"Error in connection callback: {e}")

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._connection_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._close_socket()
        
        # Clear pending queue
        while not self._send_queue.empty():
            try:
                _, callback_func = self._send_queue.get_nowait()
                if callback_func:
                    callback_func(None, 'Client stopped')
            except queue.Empty:
                break
                
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _close_socket(self):
        if self._socket_file:
            try:
                self._socket_file.close()
            except:
                pass
            self._socket_file = None
        if self._socket:
            try:
                self._socket.close()
            except:
                pass
            self._socket = None

    def send_command(self, requests, timeout=5.0):
        """
        Sends a command synchronously. Blocks the calling thread until a response is received.
        If calling from a GUI thread, use `send_command_async` instead to prevent UI freezing.
        
        Returns the parsed JSON response list from the server, or None if failed.
        """
        if not self._connected:
            return None
            
        if not isinstance(requests, list):
            requests = [requests]
            
        result_event = threading.Event()
        result_container = {}
        
        def callback(resp, err):
            result_container['response'] = resp
            result_container['error'] = err
            result_event.set()
            
        self._send_queue.put((requests, callback))
        
        if result_event.wait(timeout):
            if result_container.get('error'):
                logging.error(f"Command failed: {result_container['error']}")
                return None
            return result_container.get('response')
        else:
            logging.error("Command timed out waiting for response")
            return None

    def send_command_async(self, requests, callback):
        """
        Sends a command asynchronously. The provided callback function will be executed 
        with the response (or None if failed) once the server replies.
        
        This is perfect for GUI applications to ensure the main thread never blocks.
        """
        if not self._connected:
            if callback:
                callback(None)
            return
            
        if not isinstance(requests, list):
            requests = [requests]
            
        def _cb(resp, err):
            if err:
                logging.error(f"Async command failed: {err}")
                callback(None)
            else:
                callback(resp)
                
        self._send_queue.put((requests, _cb))

    def _connection_loop(self):
        first_message = False
        while self._running:
            if not self._connected:
                connected = False
                # The Lua script binds to the first available port in 43055-43060
                for port in range(self.start_port, self.end_port + 1):
                    try:
                        self._close_socket()
                        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        self._socket.settimeout(1.0)
                        self._socket.connect((self.host, port))
                        self._socket_file = self._socket.makefile('r', encoding='utf-8')
                        connected = True
                        break
                    except (socket.error, socket.timeout):
                        pass
                
                if not connected:
                    time.sleep(1.0)
                    continue
                
                self._set_connected(True)
                first_message = True
                
            try:
                try:
                    # The Lua script has a bug: its timeout_timer initializes to a massive negative number
                    # and will silently abandon any new connection that doesn't send a message immediately.
                    if first_message:
                        cmd_data, callback_func = self._send_queue.get_nowait()
                    else:
                        cmd_data, callback_func = self._send_queue.get(timeout=1.0)
                except queue.Empty:
                    cmd_data = [{"type": "PING"}]
                    callback_func = None
                    
                first_message = False

                # Build the payload, ensuring we append the newline needed by LuaSocket
                payload = json.dumps(cmd_data) + "\n"
                
                # Send the payload
                self._socket.settimeout(5.0)  # Wait up to 5s to send/receive a single command
                self._socket.sendall(payload.encode('utf-8'))
                
                # Receive the response using the buffered file object
                response_str = self._socket_file.readline()
                if not response_str:
                    raise socket.error("Connection closed by server cleanly")
                
                parsed = None
                err = None
                try:
                    parsed = json.loads(response_str)
                except json.JSONDecodeError:
                    parsed = response_str
                    
                # Deliver the response back to the caller
                if callback_func:
                    try:
                        callback_func(parsed, err)
                    except Exception as e:
                        logging.error(f"Error in command callback: {e}")
                    
            except socket.timeout:
                logging.error("Socket timeout during send/receive")
                self._set_connected(False)
                if 'callback_func' in locals() and callback_func:
                    callback_func(None, "Timeout")
            except Exception as e:
                logging.error(f"Socket error: {e}")
                self._set_connected(False)
                if 'callback_func' in locals() and callback_func:
                    callback_func(None, str(e))

if __name__ == "__main__":
    # Example GUI-friendly usage:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
    
    def on_connection_change(connected):
        print(f"*** Status: {'CONNECTED' if connected else 'DISCONNECTED'} ***")

    def on_response(response):
        print(f"Async Response Received: {response}")

    print("Starting Bizhawk client...")
    client = BizhawkClient()
    client.add_connection_callback(on_connection_change)
    
    try:
        while True:
            time.sleep(3)
            if client.is_connected:
                print("Sending async command...")
                client.send_command_async([{"type": "SYSTEM"}], on_response)
    except KeyboardInterrupt:
        client.stop()
