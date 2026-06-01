from dataclasses import asdict, dataclass
from typing import Dict, List


@dataclass
class ImuMessage:
    type: int
    timestamp_ns: int
    data: List[float]

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TimeMessage:
    name: str
    timestamp_ns: int
    duration_ns: int
    status: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class MotionStatusMessage:
    name: str
    timestamp_ns: int
    status: str

    def to_dict(self) -> Dict:
        return asdict(self)
