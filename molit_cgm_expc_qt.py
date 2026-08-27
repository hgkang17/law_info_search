"""예전 실행 방식과 테스트를 위한 호환 진입점.

내용은 ui/ services/ workers/ storage/ utils/ 패키지로 옮겼다.
이 파일은 기존 이름을 그대로 쓸 수 있도록 다시 내보내기만 한다.
"""

from __future__ import annotations

from main import main
from models.law import *  # noqa: F401,F403
from models.law import (  # noqa: F401
    AI_RELATED_AGENCY,
    AI_SEARCH_AGENCY,
    EXPC_AGENCY,
    PREC_AGENCY,
    RESOURCE_ALL_TARGET,
    RESOURCE_CATEGORIES,
)
from storage.cache import LawDocumentCache, SearchResultCache  # noqa: F401
from storage.paths import (  # noqa: F401
    APP_DIR,
    LAW_CACHE_DIR,
    LAW_REFERENCE_CACHE_DIR,
    LAW_REFERENCE_CACHE_SCHEMA,
    LAW_RENDER_SNAPSHOT_VERSION,
    RUNTIME_DIR,
    SEARCH_RESULT_CACHE_DIR,
)
from storage.recent import RecentSearchManager  # noqa: F401
from ui.assets import *  # noqa: F401,F403
from ui.dialogs import *  # noqa: F401,F403
from ui.main_window import LawSearchWindow  # noqa: F401
from ui.tabs.ai_search import AiLawSearchTab  # noqa: F401
from ui.tabs.law_search import LawSearchTab  # noqa: F401
from ui.tabs.resource_search import ResourceSearchTab  # noqa: F401
from ui.tabs.viewed_laws import ViewedLawsTab  # noqa: F401
from ui.theme import *  # noqa: F401,F403
from ui.widgets import *  # noqa: F401,F403
from utils.constants import DETAIL_FONT_FAMILY, FONT_FAMILY  # noqa: F401
from utils.formatting import *  # noqa: F401,F403
from utils.parsing import *  # noqa: F401,F403
from utils.patterns import *  # noqa: F401,F403
from workers.download_worker import PdfDownloadWorker  # noqa: F401
from workers.search_worker import (  # noqa: F401
    ApiWorker,
    RelatedArticleWorker,
    ResourceApiWorker,
)

__all__ = ["main", "LawSearchWindow"]


if __name__ == "__main__":
    raise SystemExit(main())
