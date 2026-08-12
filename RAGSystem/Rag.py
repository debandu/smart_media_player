from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv
import os
from langchain_core.embeddings import Embeddings
from abc import ABC, abstractmethod
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_text_splitters import TextSplitter
from langchain_core.vectorstores import VectorStore
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts.base import BasePromptTemplate
from constants import *

class RAG:

    def __init__(self, db_path: str, embedder: Embeddings = None, splitter: TextSplitter= None, vector_db: VectorStore = None, model: str = None, base_url:str = None, api_key: str = None):
        self.db_path = db_path
        self.splitter = RecursiveCharacterTextSplitter(chunk_size=200, chunk_overlap=50) if splitter is None else splitter
        self.embedder = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2") if embedder is None else embedder
        self.vector_db = (
            Chroma(persist_directory=db_path, embedding_function=self.embedder)
            if vector_db is None else vector_db
        )

    def _split_text(self, content: str):
        return self.splitter.create_documents([content])

    def store_to_db(self, content):
        self.vector_db = self.vector_db.from_documents(
            self._split_text(content),
            self.embedder,
            persist_directory=self.db_path
        )
        print("stored to vector DB!")

    def similarity_search(self, content: str, k: int = 10):
        chunks = self.vector_db.similarity_search(
            query=content, k=k
        )
        return chunks


    def retrieve_from_db(self, question: str, model: BaseChatModel = None, prompt: BasePromptTemplate = None):
        model = ChatOpenAI(model=MODEL, base_url=BASE_URL, temperature=0.3, api_key=GROQ_API_KEY) if model is None else model
        prompt = ChatPromptTemplate.from_template("""
        Answer the question only from th context below. If the context doesn't contain the answer,
        say "I don't know." Be concise and quote facts directly.

        Context:
        {context}
                                                
        Question: {question}
        """) if prompt is None else prompt
        chunks = self.similarity_search(content=question, k=10)
        context = "\n\n".join(c.page_content for c in chunks)
        chain = prompt | model
        return chain.invoke({"context": context, "question": question}).content
    
    def retrieve_timestamp_from_context(self, content: str, model: BaseChatModel = None, prompt: BasePromptTemplate = None) -> str:
        """
        Find the start timestamp (in seconds) for a scene described by `content`.
        Works purely from the vector DB context — no full transcript dict needed.
        Each stored segment must be formatted as "[Xs] text" so the LLM can read
        the timestamp directly from the retrieved chunks.
        """
        model = ChatOpenAI(model=MODEL, base_url=BASE_URL, temperature=0.3, api_key=GROQ_API_KEY) if model is None else model
        prompt = ChatPromptTemplate.from_template("""
        The context below contains timestamped transcript segments from a video.
        Each line looks like "[Xs] some dialogue" where X is the time in seconds.

        Find the segment that best matches the scene described and return ONLY the
        start time as a plain number in seconds. No units, no explanation.

        Scene to find: {content}

        Context:
        {context}
        """) if prompt is None else prompt
        chunks = self.similarity_search(content=content, k=10)
        context = "\n".join(c.page_content for c in chunks)
        chain = prompt | model
        return chain.invoke({"context": context, "content": content}).content

    def retrieve_from_db_with_start_timestamp(self, content: str, transcribed_data: dict, model: BaseChatModel = None, prompt: BasePromptTemplate = None):
        model = ChatOpenAI(model=MODEL, base_url=BASE_URL, temperature=0.3, api_key=GROQ_API_KEY) if model is None else model
        prompt = ChatPromptTemplate.from_template("""
        Below you have transcribed content from a movie, based on the portion of the movie that the user enter's return the start timestamp of that part from the transcribed content.
        NOTE: I need to pass the answer in a function that accepts the time in seconds, so return only the time and that also in seconds.                                          
        
        Transcribed_Content: {transcribed_data}
                                                  
        Context:
        {context}
                                                
        Part of the Movie: {content}
        """) if prompt is None else prompt
        chunks = self.similarity_search(content=content, k=10)
        context = "\n\n".join(c.page_content for c in chunks)
        chain = prompt | model
        return chain.invoke({"context": context, "content": content, "transcribed_data": transcribed_data}).content
        
    
