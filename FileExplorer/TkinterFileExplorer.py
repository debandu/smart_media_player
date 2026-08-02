from tkinter import Tk
import tkinter
from tkinter import filedialog
from FileExplorer.FileExplorer import FileExplorer


class TkinterFileExplorer(FileExplorer):

    def __init__(self, title: str, filetypes: list[tuple[str]]):
        self.title = title
        self.filetypes = filetypes
        self.explorer = Tk()
        self.explorer.geometry("800x600")
        frame = tkinter.Frame(self.explorer, bg="black")
        frame.pack(fill="both", expand=True)
        # self.explorer.withdraw()

    def open(self):
        file_path = filedialog.askopenfilename(title=self.title, 
                                               filetypes=self.filetypes)
        return file_path
    
    def close():
        pass
