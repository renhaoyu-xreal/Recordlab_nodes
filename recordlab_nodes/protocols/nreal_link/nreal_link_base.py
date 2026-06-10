"""
NReal Link Base - UDP data receiver
严格翻译自 nreallinkbase.h 和 nreallinkbase.cpp
"""
import struct
import socket
from typing import Optional, Callable
from dataclasses import dataclass

# Constants
NREAL_LINK_SERVER_PORT = 7099
NREAL_LINK_MAGIC_ID = 0xFD

# Enum: StateTypes (from C++ code)
class StateType:
    # List Of State Categories
    UNDEFINED_STATE = 0
    EUCLIDEAN_STATE = 1
    EUCLIDEAN_3D_STATE = 2
    SIMPLE_STATE = 3
    COMPOSITE_STATE = 4
    
    # Time Related States
    TIME_STATE = 5
    TIME_STEP = 6
    TIME_COMPENSATION_STATE = 7
    TIME_SYNC_STATE = 8
    TIME_SYNC_NOISE_STATE = 9
    RAW_TIME_DIFFERENCE = 10
    
    # Robot States
    ROBOT_STATE = 11
    
    # General Object's States
    ACTIVITY_STATE = 12
    POSE_STATE = 13
    ORIENTATION_STATE = 14
    POSITION_STATE = 15
    VELOCITY_STATE = 16
    ROTATIONAL_VELOCITY_STATE = 17
    ACCELERATION_STATE = 18
    
    # Map frame parameterization
    GLOBAL_4DOF_STATE = 19
    YAW_DIFF_STATE = 20
    PLANE_STATE = 21
    ORIENTATION_2DOF_STATE = 22
    DISTANCE_STATE = 23
    
    # Map Objects States
    EUCLIDEAN_POINT = 24
    
    # Camera States
    CAMERA_STATE = 25
    CAMERA_CALIBRATION_PARAMETERS = 26
    ROLLING_SHUTTER_TIME_STATE = 27
    FOCAL_LENGTH = 28
    CAMERA_CENTER = 29
    DISTORTION_STATE = 30
    IMAGE_DIMENSION = 31
    CAMERA_MODEL = 32
    
    # IMU states
    IMU_STATE = 33
    ACCEL_BIAS_STATE = 34
    GYRO_BIAS_STATE = 35
    NEGATIVE_GRAVITY = 36
    IMU_INTRINSICS_STATE = 37
    GYRO_SKEW_STATE = 38
    GYRO_SCALE_STATE = 39
    GYRO_G_SENSITIVITY_STATE = 40
    ACCEL_SKEW_STATE = 41
    ACCEL_SCALE_STATE = 42
    
    # Odometer states
    ODOMETER_STATE = 43
    WHEEL_BASELINE_STATE = 44
    LEFT_WHEEL_RADIUS_STATE = 45
    RIGHT_WHEEL_RADIUS_STATE = 46
    ODOM_MEAS_MULTIPLIER_STATE = 47
    
    # InterDevice States
    CAMERA_IMU_STATE = 48
    IMU_CAMERA_STATE = 49
    ODOMETER_IMU_STATE = 50
    
    # Noise States
    NOISE_STATE = 51
    
    # Information Manager Selection States
    SELECTED_STATES = 52
    CLONE_STATE = 53
    VIO_PARAMETERS_STATES = 54
    EXTRA_STATE = 55
    MARGINALIZED_STATES = 56
    ESTIMATED_STATES = 57
    OC_STATES = 58
    SLAM_STATES = 59
    PARAMETERS_STATES = 60
    FILTER_CLONES_STATES = 61
    EXTRA_STATES = 62
    
    # Estimators States
    POSE_PROPAGATION_STATE = 63
    SQRT_PROPAGATOR_STATES = 64
    SQRT_ISWF_STATES = 65
    BA_STATES = 66
    
    # Other States
    VINS_POSE_STATE = 67
    VINS_PARAMETERS_STATE = 68
    ORIENTATION_NULLSPACE_DIRECTION = 69
    VELOCITY_NULLSPACE_DIRECTION = 70
    POSITION_NULLSPACE_DIRECTION = 71
    FEATURE_NULLSPACE_DIRECTION = 72
    FIRST_ORIENTATION_LINEARIZATION_POINT = 73
    FIRST_VELOCITY_LINEARIZATION_POINT = 74
    FIRST_POSITION_LINEARIZATION_POINT = 75
    
    # Plane detection States
    PLANE_INFORMATION_STATE = 76
    
    NRLINK_MSG_POINT_CLOUD = 80
    NRLINK_MSG_PLANE_RECT = 81
    PLANE_DETECT_VERTICAL = 82
    NRLINK_MSG_PLANE_POLYGON = 83
    NRLINK_MSG_ARIPLANE_INFO = 85
    NRLINK_MSG_TRANSFORM_6DOF = 88
    NRLINK_MSG_TRANSFORM_3DOF = 89
    NRLINK_MSG_STEREO_CAMERA_PARAMS = 90
    NRLINK_MSG_ARIFRAME_INFO = 95
    NRLINK_MSG_ARIFRAME_FEATURE = 96
    NRLINK_MSG_DEPTH_SENSOR = 202
    NRLINK_MSG_KEYFRAME_INFO = 210


@dataclass
class NrealLinkMsgHeader:
    """
    #pragma pack(1)
    typedef struct _NrealLinkMsgHeader {
        uint8_t magic;
        int32_t msg_id;
        int32_t payload_length;
        uint64_t time_stamp;
    }NrealLinkMsgHeader;
    #pragma pack()
    """
    magic: int  # uint8_t
    msg_id: int  # int32_t
    payload_length: int  # int32_t
    time_stamp: int  # uint64_t
    
    SIZE = 1 + 4 + 4 + 8  # 17 bytes
    
    @classmethod
    def unpack(cls, data: bytes) -> 'NrealLinkMsgHeader':
        """解析二进制数据为消息头"""
        # '<' means little-endian
        # 'B' = uint8_t, 'i' = int32_t, 'Q' = uint64_t
        magic, msg_id, payload_length, time_stamp = struct.unpack('<BiIQ', data[:cls.SIZE])
        return cls(magic, msg_id, payload_length, time_stamp)


@dataclass
class PlotDataMessage:
    """
    typedef struct __plot_data_msg
    {
        int group_id;
        int msg_id;
        int src_id;
        QHostAddress addr = QHostAddress::Null;
        quint16 port = -1;
        QByteArray payload;
    }plot_data_message;
    """
    group_id: int
    msg_id: int
    src_id: int
    addr: str
    port: int
    payload: bytes


class NRealLinkBase:
    """
    UDP数据接收器基类
    对应 nreallinkbase.h 和 nreallinkbase.cpp
    """
    
    def __init__(self, status_dict):
        """
        NRealLinkBase::NRealLinkBase()
        """
        self.status_dict = status_dict
        self.nreal_link_socket: Optional[socket.socket] = None
        self.plot_used_index = []
        self.callback: Optional[Callable[[PlotDataMessage], None]] = None
        
    def start(self):
        """启动UDP接收器"""
        self.nreal_link_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # setSocketOption(QAbstractSocket::LowDelayOption,1)
        # UDP不支持TCP_NODELAY，跳过此选项
        
        # setSocketOption(QAbstractSocket::SendBufferSizeSocketOption, 256 * 1024)
        self.nreal_link_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256 * 1024)
        
        # setSocketOption(QAbstractSocket::ReceiveBufferSizeSocketOption, 512 * 1024)
        self.nreal_link_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512 * 1024)
        
        # bind(NREAL_LINK_SERVER_PORT, QUdpSocket::ShareAddress)
        self.nreal_link_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # 明确绑定到 0.0.0.0 (IPv4)
        self.nreal_link_socket.bind(('0.0.0.0', NREAL_LINK_SERVER_PORT))
        # print(f"[DEBUG] UDP socket bound to 0.0.0.0:{NREAL_LINK_SERVER_PORT}")
        
        # 启动接收线程
        import threading
        self.receive_thread = threading.Thread(target=self.udp_get_message, daemon=True)
        self.receive_thread.start()

        self.status_dict['udp_started'] = True
        # print(f"[DEBUG] UDP receive thread started")
        
    def stop(self):
        """停止UDP接收器"""
        if self.nreal_link_socket:
            self.nreal_link_socket.close()
            self.nreal_link_socket = None
    
    def udp_get_message(self):
        """
        void NRealLinkBase::udpGetMessage()
        接收UDP消息
        """
        # print("[DEBUG] UDP receive loop started")
        while self.nreal_link_socket:
            try:
                # hasPendingDatagrams() + pendingDatagramSize() + readDatagram()
                data, (addr, port) = self.nreal_link_socket.recvfrom(65536 + 64)
                datagram_size = len(data)
                
                if datagram_size > NrealLinkMsgHeader.SIZE:
                    header = NrealLinkMsgHeader.unpack(data)
                    if header.payload_length + NrealLinkMsgHeader.SIZE == datagram_size:
                        self.plot_data_dispatch(data, addr, port)
                        
            except socket.timeout:
                continue  # 超时后继续等待
            except Exception as e:
                if self.nreal_link_socket:  # 只有在socket还存在时才报错
                    print(f"Error receiving UDP message: {e}")
                break
        # print("[DEBUG] UDP receive loop stopped")
    
    def plot_data_dispatch(self, buffer: bytes, addr: str, port: int):
        """
        void NRealLinkBase::PlotDataDispatch(uint8_t *buffer, QHostAddress &addr, quint16 &port)
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
        
        print(f"[UDP-DEBUG] Received PlotDataMessage: group_id={m_plot_data.group_id}, msg_id={m_plot_data.msg_id}, payload_length={header.payload_length}, from {addr}:{port}")

        if header.payload_length > 0:
            # payload包含time_stamp (sizeof(uint64_t)) + 实际payload数据
            # memcpy(m_plot_data.payload.data(), buffer + sizeof(NrealLinkMsgHeader) - sizeof(uint64_t), 
            #        msg->payload_length + sizeof(uint64_t));
            start_offset = NrealLinkMsgHeader.SIZE - 8  # sizeof(uint64_t) = 8
            end_offset = start_offset + header.payload_length + 8
            m_plot_data.payload = buffer[start_offset:end_offset]
            
            # emit setPlotData(m_plot_data)
            print(f"[UDP-DEBUG] Callback is set: {self.callback is not None}, calling callback...")
            if self.callback:
                self.callback(m_plot_data)
                print(f"[UDP-DEBUG] Callback executed")
            else:
                print(f"[UDP-DEBUG] No callback set!")
    
    def set_plot_data_callback(self, callback: Callable[[PlotDataMessage], None]):
        """设置数据回调函数"""
        print(f"[UDP-DEBUG] Setting callback: {callback}")
        self.callback = callback
        print(f"[UDP-DEBUG] Callback set successfully: {self.callback}")
