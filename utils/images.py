"""본문에 끼워 넣는 원문 그림 다듬기.

법제처가 주는 표ㆍ도면 그림에는 아래쪽에 빈 종이가 그대로 붙어 오는 것이
있다. 그대로 그리면 그림 아래에 이유를 알 수 없는 흰 칸이 남아, 다음 항목이
한참 밑으로 밀린다. 실제로 그려진 부분만 남기고 빈 종이는 잘라 낸다.
"""

from __future__ import annotations

import base64
import hashlib

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage, qGray


# 이 밝기보다 밝으면 빈 종이로 본다. 흰 종이 스캔본은 250 안팎이라
# 여유를 조금 둔다.
BLANK_LEVEL = 246

# 한 줄이 비었는지 볼 때 찍어 보는 점의 최대 개수. 표 테두리처럼 가는 선을
# 놓치지 않을 만큼 촘촘하되, 큰 그림에서도 빠르게 끝나는 값이다.
ROW_SAMPLES = 160

# 아래 빈 칸이 이 비율보다 작으면 그냥 둔다. 몇 픽셀을 잘라 봐야 화면에서
# 달라지는 것이 없고, 다시 인코딩하는 값만 든다. 손볼 만한 것은 그림
# 높이의 십분의 일이 넘게 비어 있는 경우다.
MIN_TRIM_RATIO = 0.1

# 잘라 낸 뒤에도 이 비율만큼은 남아야 한다. 온통 밝은 그림을 통째로
# 날리는 일을 막는 안전장치다.
MIN_KEEP_RATIO = 0.2

# 잘라 낸 자리에 남겨 두는 여백. 글자 아래끝이 바싹 잘려 보이지 않게 한다.
BOTTOM_PADDING = 6


_cache: dict[str, str] = {}


def _row_is_blank(image: QImage, y: int) -> bool:
    width = image.width()
    step = max(1, width // ROW_SAMPLES)
    for x in range(0, width, step):
        if qGray(image.pixel(x, y)) < BLANK_LEVEL:
            return False
    # 오른쪽 끝은 위 반복이 건너뛸 수 있어 따로 본다.
    return qGray(image.pixel(width - 1, y)) >= BLANK_LEVEL


def _to_data_uri(image: QImage) -> str:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        return ""
    encoded = base64.b64encode(bytes(buffer.data())).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def trim_blank_bottom(uri: str) -> str:
    """그림 아래에 붙은 빈 종이를 잘라 낸 data URI를 돌려준다.

    잘라 낼 것이 없거나 그림을 읽지 못하면 받은 값을 그대로 돌려준다.
    같은 그림을 여러 번 그릴 수 있으므로 결과를 기억해 둔다.
    """
    if not uri.startswith("data:image/") or "," not in uri:
        return uri
    key = hashlib.sha1(uri.encode("utf-8", "ignore")).hexdigest()
    cached = _cache.get(key)
    if cached is not None:
        return cached

    payload = uri.split(",", 1)[1]
    image = QImage()
    if not image.loadFromData(QByteArray.fromBase64(payload.encode("ascii"))):
        _cache[key] = uri
        return uri
    height = image.height()
    if height < 40 or image.width() < 8:
        _cache[key] = uri
        return uri

    bottom = height
    while bottom > 1 and _row_is_blank(image, bottom - 1):
        bottom -= 1
    trimmed = height - bottom
    keep = min(height, bottom + BOTTOM_PADDING)
    if (
        trimmed < height * MIN_TRIM_RATIO
        or keep < height * MIN_KEEP_RATIO
        or keep >= height
    ):
        _cache[key] = uri
        return uri

    cropped = _to_data_uri(image.copy(0, 0, image.width(), keep))
    result = cropped or uri
    _cache[key] = result
    return result
