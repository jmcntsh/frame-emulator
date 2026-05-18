"""Import-compatible names for current Python Frame SDK samples.

Sample apps can switch from physical hardware to the emulator by changing:

    from frame_msg import FrameMsg, TxPlainText

to:

    from frame_emulator.compat import FrameMsg, TxPlainText
"""

from .sdk import FrameBleEmulator as FrameBle
from .sdk import FrameMsgEmulator as FrameMsg
from .sdk import TxPlainText, TxSprite

__all__ = ["FrameBle", "FrameMsg", "TxPlainText", "TxSprite"]
