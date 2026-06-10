"""
Payload Parser - 根据plot.json精确解析payload
严格对应C++: qplotengine.h:48-82
"""
import struct
import json
from typing import List, Dict, Tuple


class PayloadParser:
    """
    根据plot.json的struct定义解析payload
    
    对应C++中的rawToValue函数:
    - raw_u8:  1字节
    - raw_s8:  1字节
    - raw_u16: 2字节
    - raw_s16: 2字节
    - raw_u32: 4字节
    - raw_s32: 4字节
    - raw_u64: 8字节
    - raw_s64: 8字节
    - raw_f32: 4字节
    - raw_f64: 8字节
    """
    
    # 类型到struct格式和字节数的映射
    TYPE_MAP = {
        'u8':  ('<B', 1),  # unsigned char
        's8':  ('<b', 1),  # signed char
        'u16': ('<H', 2),  # unsigned short
        's16': ('<h', 2),  # signed short
        'u32': ('<I', 4),  # unsigned int
        's32': ('<i', 4),  # signed int
        'u64': ('<Q', 8),  # unsigned long long
        's64': ('<q', 8),  # signed long long
        'f32': ('<f', 4),  # float
        'f64': ('<d', 8),  # double
    }
    
    def __init__(self, plot_json_path: str = "plot.json"):
        """加载plot.json配置"""
        with open(plot_json_path, 'r') as f:
            self.config = json.load(f)
        
        # 预处理：为每个消息类型创建解析模板
        self.parse_templates = {}
        for msg_name, msg_config in self.config.items():
            group_id = msg_config.get('GROUP_ID', 0)
            msg_id = msg_config.get('MSG_ID', 0)
            struct_fields = msg_config.get('struct', [])
            
            # 解析struct定义
            template = self._build_parse_template(struct_fields)
            key = (group_id, msg_id)
            self.parse_templates[key] = template
    
    def _build_parse_template(self, struct_fields: List[str]) -> List[Tuple[str, int, int]]:
        """
        构建解析模板
        返回: [(format, size, count), ...]
        """
        template = []
        
        for field in struct_fields:
            field = field.strip()
            parts = field.split()
            
            if len(parts) < 2:
                continue
            
            type_str = parts[0]
            name_part = parts[1]
            
            # 检查是否是数组 data[6]
            if '[' in name_part and ']' in name_part:
                name = name_part.split('[')[0]
                size_str = name_part.split('[')[1].split(']')[0]
                try:
                    array_size = int(size_str)
                except:
                    array_size = 1
            else:
                array_size = 1
            
            # 获取类型信息
            if type_str in self.TYPE_MAP:
                fmt, byte_size = self.TYPE_MAP[type_str]
                template.append((fmt, byte_size, array_size))
        
        return template
    
    def parse(self, group_id: int, msg_id: int, payload: bytes) -> List[float]:
        """
        根据group_id和msg_id解析payload
        
        严格对应C++: qplotengine.cpp:541
        double value_i = group->items[i].setData(timestamp, &p_raw);
        """
        key = (group_id, msg_id)
        
        if key not in self.parse_templates:
            # 没有配置，尝试通用解析
            return self._parse_generic(payload)
        
        template = self.parse_templates[key]
        data_items = []
        offset = 0
        
        try:
            for fmt, byte_size, count in template:
                for _ in range(count):
                    if offset + byte_size > len(payload):
                        # 数据不够，返回已解析的
                        return data_items
                    
                    # 解析一个值
                    value = struct.unpack(fmt, payload[offset:offset+byte_size])[0]
                    data_items.append(float(value))
                    offset += byte_size
            
            return data_items
            
        except Exception as e:
            print(f"Error parsing payload: {e}")
            return data_items
    
    def _parse_generic(self, payload: bytes) -> List[float]:
        """通用解析：先按u64，剩余按f32"""
        data_items = []
        offset = 0
        
        # 按8字节解析
        while offset + 8 <= len(payload):
            value = struct.unpack('<Q', payload[offset:offset+8])[0]
            data_items.append(float(value))
            offset += 8
        
        # 剩余按4字节解析
        while offset + 4 <= len(payload):
            value = struct.unpack('<f', payload[offset:offset+4])[0]
            data_items.append(float(value))
            offset += 4
        
        return data_items
    
    def get_field_names_for_message(self, group_id: int, msg_id: int) -> List[str]:
        """获取消息的字段名列表"""
        # 查找匹配的消息配置
        for msg_name, config in self.config.items():
            if config.get('GROUP_ID') == group_id and config.get('MSG_ID') == msg_id:
                # 从 struct 解析字段名
                field_names = []
                for field_str in config.get('struct', []):
                    parts = field_str.strip().split()
                    if len(parts) >= 2:
                        field_name = parts[1]
                        # 处理数组 data[6]
                        if '[' in field_name and ']' in field_name:
                            base_name = field_name[:field_name.index('[')]
                            size_str = field_name[field_name.index('[')+1:field_name.index(']')]
                            try:
                                size = int(size_str)
                                for i in range(size):
                                    field_names.append(f"{base_name}_{i}")
                            except:
                                field_names.append(base_name)
                        else:
                            field_names.append(field_name)
                return field_names
        
        return []


# 测试
if __name__ == "__main__":
    parser = PayloadParser()
    
    # 测试air_data
    print("=== Test air_data parsing ===")
    # 构造测试payload: 3个u64 + 1个u32 + 6个f32
    import struct
    test_payload = struct.pack('<QQQIffffff', 
                              1000, 2000, 3000,  # 3个u64
                              123,                # 1个u32
                              1.1, 2.2, 3.3, 4.4, 5.5, 6.6)  # 6个f32
    
    result = parser.parse(127, 1, test_payload)  # air_data: GROUP_ID=127, MSG_ID=1
    print(f"Expected: [1000.0, 2000.0, 3000.0, 123.0, 1.1, 2.2, 3.3, 4.4, 5.5, 6.6]")
    print(f"Got:      {result}")
    print(f"Payload size: {len(test_payload)} bytes")
    print(f"Parsed {len(result)} values")
