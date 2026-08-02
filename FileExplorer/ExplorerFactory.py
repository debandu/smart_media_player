from .TkinterFileExplorer import TkinterFileExplorer
from .FileExplorer import FileExplorer
class ExploreFactory:

    @classmethod
    def get_explorer(cls, name: str) -> FileExplorer:
        if(name=="tk"):
            return TkinterFileExplorer
        
        return TkinterFileExplorer