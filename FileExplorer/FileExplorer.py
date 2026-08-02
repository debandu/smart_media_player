from abc import abstractmethod, ABC

class FileExplorer(ABC):

    title: str
    filetypes: list[tuple[str]]

    @abstractmethod
    def open():
        pass

    @abstractmethod
    def close():
        pass