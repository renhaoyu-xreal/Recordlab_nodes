"""
NReal Link TCP - TCP data receiver
严格翻译自 nreallinktcp.h 和 nreallinktcp.cpp
"""
import struct
import socket
import threading
from typing import List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime

from .nreal_link_base import NrealLinkMsgHeader, PlotDataMessage

# Constants
NREAL_LINK_TCP_SERVER_PORT = 8099


@dataclass
class TcpMsgHeader:
    """
    #pragma pack(1)
    typedef struct TcpMsgHeader {
        uint8_t version;
        uint8_t magic_num;
        uint8_t serialize_method;
        uint8_t service_num;
        uint8_t msg_type;
        uint32_t msg_count;
        uint32_t length;
        uint64_t timestamp_ns;
        uint64_t packet_id;
        uint8_t crc;
    } TcpMsgHeader;
    #pragma pack()
    """
    version: int  # uint8_t
    magic_num: int  # uint8_t
    serialize_method: int  # uint8_t
    service_num: int  # uint8_t
    msg_type: int  # uint8_t
    msg_count: int  # uint32_t
    length: int  # uint32_t
    timestamp_ns: int  # uint64_t
    packet_id: int  # uint64_t
    crc: int  # uint8_t
    
    SIZE = 1 + 1 + 1 + 1 + 1 + 4 + 4 + 8 + 8 + 1  # 30 bytes


class TcpPacketMsgHeader:
    """
    union TcpPacketMsgHeader {
      uint8_t header;
      struct data {
        uint8_t submsg_type : 1;  // 0:header, 1:data
        uint8_t reserved : 7;
      } data;
    };
    """
    SUBMSG_TYPE_HEADER = 0
    SUBMSG_TYPE_DATA = 1
    
    def __init__(self, header_byte: int):
        self.header = header_byte
        self.submsg_type = header_byte & 0x01
        self.reserved = (header_byte >> 1) & 0x7F


class NrealLinkData:
    """
    struct NrealLinkData {
      union {
        float header[11];
        struct {
          uint64_t onsensor_timestamp_us;
          uint64_t timestampe_ns;
          uint32_t type;
          float data[6];
        };
      };
    };
    """
    pass


class NvizSensorData:
    """
    struct NvizSensorData {
      int group_id;
      int msg_id;
      NrealLinkData data;
    };
    """
    pass


class TcpParserStatus:
    """
    typedef enum TcpParserStatus
    {
        ON_PARSER_INIT = 0,
        ON_PARSER_HEAD = 1,
        ON_PARSER_BODY = 2,
    }TcpParserStatus;
    """
    ON_PARSER_INIT = 0
    ON_PARSER_HEAD = 1
    ON_PARSER_BODY = 2


def crc8(data: bytes) -> int:
    """
    CRC8校验算法
    uint8_t crc8(uint8_t *data, int size)
    """
    crc = 0x00
    poly = 0x07
    
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ poly) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    
    return crc


class TcpClientSocket:
    """
    用来通信的类TcpClientSocket
    对应 nreallinktcp.cpp 中的 TcpClientSocket
    """
    
    # enum SubmsgType
    SUBMSG_TYPE_HEADER = 0
    SUBMSG_TYPE_DATA = 1
    
    # enum PacketContentType
    PACKET_CONTENT_TYPE_SENSOR_DATA = 1
    
    def __init__(self, client_socket: socket.socket, client_address: tuple, callback: Callable):
        self.client_socket = client_socket
        self.client_address = client_address
        self.callback = callback
        
        # Constants
        self.m_TCP_MAGIC_NUM = 239
        self.m_TCP_MAX_FREQ_COUNT = 50000
        
        # State variables
        self.mCurHeader = None
        self.mLastSuccessHeaderTimestamp = 0
        self.mResponseContentType = 0
        self.mCurParserStatus = TcpParserStatus.ON_PARSER_INIT
        self.mCurReserved = bytearray()
        
        # Start receive thread
        self.running = True
        self.receive_thread = threading.Thread(target=self.receive_data, daemon=True)
        self.receive_thread.start()
    
    def get_buffer_size(self) -> int:
        """获取当前TCP接收缓冲区大小"""
        return len(self.mCurReserved)
    
    def close(self):
        """关闭客户端连接"""
        self.running = False
        if self.client_socket:
            try:
                self.client_socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self.client_socket.close()
            except Exception:
                pass
        # daemon线程会自动退出，不需要join
    
    def parser_head(self) -> tuple[bool, bool]:
        """
        bool TcpClientSocket::parserHead(uint8_t** curDataPtrPtr,uint32_t& curLen, 
                                         uint32_t& parserLen, bool& parserBreak)
        用于解析消息头
        返回: (success, parser_break)
        """
        TcpMsgSize = TcpMsgHeader.SIZE
        
        if len(self.mCurReserved) < TcpMsgSize:
            return True, True  # 数据不够，等待更多数据
        
        # 解析头部
        data = self.mCurReserved
        cur_idx = 0
        
        version = data[cur_idx]
        cur_idx += 1
        
        magic_num = data[cur_idx]
        cur_idx += 1
        
        # 判断校验信息
        if self.m_TCP_MAGIC_NUM != magic_num:
            print(f"magic_num check failed. magic_num in header: {magic_num}")
            return False, False
        
        serialize_method = data[cur_idx]
        cur_idx += 1
        
        service_num = data[cur_idx]
        cur_idx += 1
        
        msg_type = data[cur_idx]
        cur_idx += 1
        
        msg_count = struct.unpack('<I', data[cur_idx:cur_idx+4])[0]
        cur_idx += 4
        
        length = struct.unpack('<I', data[cur_idx:cur_idx+4])[0]
        cur_idx += 4
        
        timestamp_ns = struct.unpack('<Q', data[cur_idx:cur_idx+8])[0]
        cur_idx += 8
        
        packet_id = struct.unpack('<Q', data[cur_idx:cur_idx+8])[0]
        cur_idx += 8
        
        crc_received = data[cur_idx]
        cur_idx += 1
        
        # 计算CRC
        header_bytes = struct.pack('<BBBBBIIQQB', 
                                   version, magic_num, serialize_method, service_num, msg_type,
                                   msg_count, length, timestamp_ns, packet_id, 0)
        crc_compute = crc8(header_bytes)
        
        # 判断校验crc信息
        if crc_received != crc_compute:
            print(f"crc check failed. crc: {crc_received} crc_compute: {crc_compute}")
            return False, False
        
        # 保存头部
        self.mCurHeader = TcpMsgHeader(
            version=version,
            magic_num=magic_num,
            serialize_method=serialize_method,
            service_num=service_num,
            msg_type=msg_type,
            msg_count=msg_count,
            length=length,
            timestamp_ns=timestamp_ns,
            packet_id=packet_id,
            crc=crc_received
        )
        
        # 判断数据长度是否超过指定的大小
        if self.mCurHeader.msg_count > self.m_TCP_MAX_FREQ_COUNT:
            return False, False
        
        self.mCurParserStatus = TcpParserStatus.ON_PARSER_HEAD
        
        # 删除已解析的数据
        self.mCurReserved = self.mCurReserved[TcpMsgSize:]
        
        return True, False
    
    def parser_body(self) -> tuple[bool, bool, List[bytearray]]:
        """
        bool TcpClientSocket::parserBody(uint8_t** curDataPtrPtr, 
                                         QVector< QVector<uint8_t> >& allSensorDatas,
                                         uint32_t& curLen, uint32_t& parserLen, 
                                         bool& parserBreak, QHostAddress &addr, quint16 &port)
        用于解析消息体
        返回: (success, parser_break, all_sensor_datas)
        """
        TcpMsgSize = TcpMsgHeader.SIZE
        bodySize = self.mCurHeader.length - TcpMsgSize
        
        if len(self.mCurReserved) < bodySize:
            return True, True, []  # 数据还没有完全到达
        
        all_sensor_datas = [] #这里是拆包以后，每个小包的内容
        data = self.mCurReserved
        cur_idx = 0
        
        while cur_idx < bodySize:
            # 先解析消息头部,拿到payload_length
            if cur_idx + NrealLinkMsgHeader.SIZE > len(data):
                break
            
            header = NrealLinkMsgHeader.unpack(data[cur_idx:])
            PerSensorDataSize = NrealLinkMsgHeader.SIZE + header.payload_length
            
            # 再把整个消息的全部内容拿到
            if cur_idx + PerSensorDataSize > len(data):
                break
            
            sensor_data = bytearray(data[cur_idx:cur_idx + PerSensorDataSize])
            all_sensor_datas.append(sensor_data)
            
            cur_idx += PerSensorDataSize
        
        cur_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if len(all_sensor_datas) != self.mCurHeader.msg_count:
            print(f"[{cur_datetime}] !bad freq_count. allSensorDatas.size(): {len(all_sensor_datas)} "
                  f"header's freq_count: {self.mCurHeader.msg_count} "
                  f"addr: {self.client_address[0]} port: {self.client_address[1]}")
            return False, False, []
        
        self.mCurParserStatus = TcpParserStatus.ON_PARSER_BODY
        
        # 删除已解析的数据
        self.mCurReserved = self.mCurReserved[bodySize:]
        
        return True, False, all_sensor_datas
    
    def response_to_client(self):
        """
        void TcpClientSocket::ResponseToClient()
        TRY response message to client
        """
        try:
            if self.mResponseContentType == 1:
                self.client_socket.sendall(b"ok,stop_collect")
            else:
                self.client_socket.sendall(b"ok")
        except Exception as e:
            print(f"Error sending response: {e}")
    
    def receive_data(self):
        """
        void TcpClientSocket::receiveData()
        处理readyRead信号读取数据
        """
        while self.running:
            try:
                # 接收数据
                data = self.client_socket.recv(65536)
                if not data:
                    break
                
                # 根据tcp_packet_msg_header判断数据类型
                if len(data) < 1:
                    continue
                
                tcp_packet_msg_header = TcpPacketMsgHeader(data[0])
                data = data[1:]  # 跳过TcpPacketMsgHeader
                
                # 检查消息类型是否符合预期
                if (self.mCurParserStatus == TcpParserStatus.ON_PARSER_INIT or 
                    self.mCurParserStatus == TcpParserStatus.ON_PARSER_BODY):
                    # 该解析header了
                    if tcp_packet_msg_header.submsg_type != self.SUBMSG_TYPE_HEADER:
                        # 收到DATA包但期望HEADER包 - 丢弃这个recv的所有数据，继续等待下一个recv
                        # 这样可以跳过错误的DATA包，等待正确的HEADER包
                        continue
                
                if self.mCurParserStatus == TcpParserStatus.ON_PARSER_HEAD:
                    # header解析完毕，该解析body了
                    if tcp_packet_msg_header.submsg_type == self.SUBMSG_TYPE_HEADER:
                        print(f"check body but comes header. bad type. submsg_type: {tcp_packet_msg_header.submsg_type}")
                        self.mCurReserved.clear()
                        self.mCurParserStatus = TcpParserStatus.ON_PARSER_BODY
                
                # 将接收到的数据添加到缓冲区
                self.mCurReserved.extend(data)
                
                # 解析数据
                while len(self.mCurReserved) > 0:
                    # 解析header
                    if (self.mCurParserStatus == TcpParserStatus.ON_PARSER_INIT or 
                        self.mCurParserStatus == TcpParserStatus.ON_PARSER_BODY):
                        
                        success, parser_break = self.parser_head()
                        
                        if not success:
                            self.mCurReserved.clear()
                            self.response_to_client()
                            break
                        
                        if parser_break:
                            break
                        
                        if self.mCurHeader.timestamp_ns == self.mLastSuccessHeaderTimestamp:
                            # 如果发送了重复的消息，扔掉
                            self.mCurReserved.clear()
                            self.response_to_client()
                            break
                        
                        self.response_to_client()
                        break
                    
                    # 解析完成header，开始解析body
                    if self.mCurParserStatus == TcpParserStatus.ON_PARSER_HEAD:
                        #all_sensor_datas 是拆包以后，每个小包的内容
                        success, parser_break, all_sensor_datas = self.parser_body()
                        
                        if not success:
                            self.mCurReserved.clear()
                            self.response_to_client()
                            break
                        
                        if parser_break:
                            self.response_to_client()  # 必须回复"ok"，否则发送端会阻塞
                            break
                        
                        self.response_to_client()
                        
                        # 这时，一个完整的消息算是处理完了
                        self.mLastSuccessHeaderTimestamp = self.mCurHeader.timestamp_ns
                        
                        # 调用回调处理数据
                        if self.callback:
                            self.callback(self.client_address[0], self.client_address[1], 
                                        self.mCurHeader.msg_type, all_sensor_datas)
                        break
                
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error in receive_data: {e}")
                break
    
    def on_update_response_content_type(self, response_content_type: int):
        """
        void TcpClientSocket::onUpdateResponseContentType(uint8_t responseContentType)
        """
        self.mResponseContentType = response_content_type


class NrealLinkTcpServer:
    """
    TCP服务器
    对应 nreallinktcp.cpp 中的 NrealLinkTcpServer
    """
    
    def __init__(self, status_dict):
        self.status_dict = status_dict
        self.server_socket: Optional[socket.socket] = None
        self.tcp_client_socket_list: List[TcpClientSocket] = []
        self.running = False
        self.accept_thread: Optional[threading.Thread] = None
        self.callback: Optional[Callable[[PlotDataMessage], None]] = None
        self.connection_callback: Optional[Callable[[tuple], None]] = None  # 连接建立时的回调
    
    def start(self):
        """
        NrealLinkTcpServer::NrealLinkTcpServer(QObject *parent)
        启动TCP服务器
        """
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # 设置端口可重用，避免TIME_WAIT状态占用
            try:
                self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except AttributeError:
                pass  # SO_REUSEPORT在某些系统上不可用
            
            # listen(QHostAddress::Any, NREAL_LINK_TCP_SERVER_PORT)
            self.server_socket.bind(('', NREAL_LINK_TCP_SERVER_PORT))
            self.server_socket.listen(5)
            
            self.running = True
            self.accept_thread = threading.Thread(target=self.accept_connections, daemon=True)
            self.accept_thread.start()
            self.status_dict['tcp_started'] = True
        except OSError as e:
            print(f"[TCP-ERROR] Failed to start TCP server: {e}")
            raise
    
    def stop(self):
        """
        NrealLinkTcpServer::~NrealLinkTcpServer()
        停止TCP服务器
        """
        self.running = False
        
        # 关闭服务器socket（会让accept()抛异常并退出）
        if self.server_socket:
            try:
                self.server_socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None
        
        # 关闭所有客户端连接
        for client in self.tcp_client_socket_list[:]:
            try:
                client.close()
            except Exception:
                pass
        self.tcp_client_socket_list.clear()
        
        # daemon线程会自动退出，不需要join
    
    def accept_connections(self):
        """接受新的客户端连接"""
        self.server_socket.settimeout(1.0)
        
        while self.running:
            try:
                client_socket, client_address = self.server_socket.accept()
                self.incoming_connection(client_socket, client_address)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"Error accepting connection: {e}")
                break
    
    def incoming_connection(self, client_socket: socket.socket, client_address: tuple):
        """
        void NrealLinkTcpServer::incomingConnection(qintptr socketDescriptor)
        只要出现一个新的连接，就会自动调用这个函数
        """
        # 调用连接回调（如果设置了）
        if self.connection_callback:
            try:
                self.connection_callback(client_address)
            except Exception as e:
                print(f"[TCP-ERROR] Connection callback error: {e}")
        
        # 创建新的通信套接字
        tcp_client_socket = TcpClientSocket(
            client_socket, 
            client_address,
            self.slot_client_update_server
        )
        
        # 设置socket选项
        try:
            tcp_client_socket.client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            tcp_client_socket.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256 * 1024)
            tcp_client_socket.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512 * 1024)
        except Exception as e:
            print(f"Error setting socket options: {e}")
        
        # 将这个套接字加入客户端套接字列表中
        self.tcp_client_socket_list.append(tcp_client_socket)
        
        cur_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{cur_datetime}] New TCP connection from {client_address[0]}:{client_address[1]}")
    
    def slot_client_update_server(self, addr: str, port: int, msg_type: int, 
                                   all_sensor_datas: List[bytearray]):
        """
        void NrealLinkTcpServer::slotClientUpdateServer(QHostAddress addr, quint16 port, 
                                                        uint8_t msg_type, 
                                                        QVector< QVector<uint8_t> > allSensorDatas)
        用来处理TcpClientSocket发过来的信号
        """
        for i, sensor_data in enumerate(all_sensor_datas):
            data_len = len(sensor_data)
            
            if data_len > NrealLinkMsgHeader.SIZE:
                header = NrealLinkMsgHeader.unpack(bytes(sensor_data))
                if header.payload_length + NrealLinkMsgHeader.SIZE == data_len:
                    self.plot_data_dispatch(bytes(sensor_data), addr, port)
    
    def plot_data_dispatch(self, buffer: bytes, addr: str, port: int):
        """
        void NrealLinkTcpServer::PlotDataDispatch(uint8_t *buffer, QHostAddress &addr, quint16 &port)
        分发接收到的数据
        """
        header = NrealLinkMsgHeader.unpack(buffer)
        
        m_plot_data = PlotDataMessage(
            group_id=header.magic,
            msg_id=header.msg_id,
            src_id=0,
            addr=addr,
            port=port,
            payload=b''
        )
        
        if header.payload_length > 0:
            # payload包含time_stamp (sizeof(uint64_t)) + 实际payload数据
            start_offset = NrealLinkMsgHeader.SIZE - 8
            end_offset = start_offset + header.payload_length + 8
            m_plot_data.payload = buffer[start_offset:end_offset]
            
            # emit setPlotData(m_plot_data)
            if self.callback:
                self.callback(m_plot_data)
    
    def on_update_tcp_client_response_content_type(self, response_content_type: int):
        """
        void NrealLinkTcpServer::onUpdateTcpClientResponseContentType(uint8_t responseContentType)
        """
        for client in self.tcp_client_socket_list:
            client.on_update_response_content_type(response_content_type)
    
    def set_plot_data_callback(self, callback: Callable[[PlotDataMessage], None]):
        """设置数据回调函数"""
        self.callback = callback
    
    def set_connection_callback(self, callback: Callable[[tuple], None]):
        """设置连接建立时的回调函数
        
        Args:
            callback: 回调函数，接收 (ip, port) 元组作为参数
        """
        self.connection_callback = callback
    
    def get_total_buffer_size(self) -> int:
        """获取所有客户端TCP接收缓冲区的总大小"""
        total = 0
        for client in self.tcp_client_socket_list:
            total += client.get_buffer_size()
        return total
