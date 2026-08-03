"""Tests for RAGSystem/Rag.py."""

from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from RAGSystem.Rag import RAG


class TestRAGInit:
    def test_uses_provided_splitter_and_embedder(self):
        mock_splitter = MagicMock()
        mock_embedder = MagicMock()
        mock_vdb = MagicMock()

        rag = RAG(
            db_path="/tmp/db",
            embedder=mock_embedder,
            splitter=mock_splitter,
            vector_db=mock_vdb,
        )
        assert rag.splitter is mock_splitter
        assert rag.embedder is mock_embedder
        assert rag.vector_db is mock_vdb

    def test_defaults_created_when_none_provided(self):
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        mock_vdb = MagicMock()
        with patch("RAGSystem.Rag.HuggingFaceEmbeddings") as mock_hfe, \
             patch("RAGSystem.Rag.Chroma", return_value=mock_vdb):
            rag = RAG(db_path="/tmp/db")

        assert isinstance(rag.splitter, RecursiveCharacterTextSplitter)
        mock_hfe.assert_called_once()


class TestRAGSplitText:
    def _make_rag(self):
        mock_splitter = MagicMock()
        mock_vdb = MagicMock()
        return RAG(
            db_path="/tmp/db",
            embedder=MagicMock(),
            splitter=mock_splitter,
            vector_db=mock_vdb,
        )

    def test_split_text_calls_splitter(self):
        rag = self._make_rag()
        rag._split_text("some content")
        rag.splitter.create_documents.assert_called_once_with(["some content"])

    def test_split_text_returns_splitter_result(self):
        rag = self._make_rag()
        fake_docs = [Document(page_content="chunk1"), Document(page_content="chunk2")]
        rag.splitter.create_documents.return_value = fake_docs
        result = rag._split_text("some content")
        assert result == fake_docs


class TestRAGStoreToDb:
    def _make_rag(self):
        mock_splitter = MagicMock()
        mock_splitter.create_documents.return_value = [Document(page_content="chunk")]
        mock_vdb = MagicMock()
        rag = RAG(
            db_path="/tmp/db",
            embedder=MagicMock(),
            splitter=mock_splitter,
            vector_db=mock_vdb,
        )
        return rag, mock_vdb

    def test_store_to_db_calls_from_documents(self):
        rag, mock_vdb = self._make_rag()
        mock_vdb.from_documents.return_value = mock_vdb
        rag.store_to_db("Transcribed video content.")
        mock_vdb.from_documents.assert_called_once()

    def test_store_to_db_updates_vector_db(self):
        rag, mock_vdb = self._make_rag()
        new_vdb = MagicMock()
        mock_vdb.from_documents.return_value = new_vdb
        rag.store_to_db("content")
        assert rag.vector_db is new_vdb


class TestRAGSimilaritySearch:
    def _make_rag(self):
        mock_vdb = MagicMock()
        rag = RAG(db_path="/tmp/db", embedder=MagicMock(),
                  splitter=MagicMock(), vector_db=mock_vdb)
        return rag, mock_vdb

    def test_similarity_search_delegates_to_vector_db(self):
        rag, mock_vdb = self._make_rag()
        fake_chunks = [Document(page_content="result")]
        mock_vdb.similarity_search.return_value = fake_chunks

        result = rag.similarity_search("query", k=5)
        mock_vdb.similarity_search.assert_called_once_with(query="query", k=5)
        assert result == fake_chunks

    def test_similarity_search_default_k_is_10(self):
        rag, mock_vdb = self._make_rag()
        mock_vdb.similarity_search.return_value = []
        rag.similarity_search("test")
        _, kwargs = mock_vdb.similarity_search.call_args
        assert kwargs["k"] == 10


class TestRAGRetrieveFromDb:
    def _make_rag_with_chunks(self, chunks):
        mock_vdb = MagicMock()
        mock_vdb.similarity_search.return_value = chunks
        rag = RAG(db_path="/tmp/db", embedder=MagicMock(),
                  splitter=MagicMock(), vector_db=mock_vdb)
        return rag

    def test_retrieve_from_db_uses_custom_model_and_prompt(self):
        chunks = [Document(page_content="ctx")]
        rag = self._make_rag_with_chunks(chunks)

        mock_model = MagicMock()
        mock_prompt = MagicMock()
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = MagicMock(content="Answer here")
        mock_prompt.__or__ = MagicMock(return_value=mock_chain)

        result = rag.retrieve_from_db(
            question="What happened?",
            model=mock_model,
            prompt=mock_prompt,
        )
        mock_prompt.__or__.assert_called_once_with(mock_model)
        mock_chain.invoke.assert_called_once()
        assert result == "Answer here"

    def test_retrieve_from_db_with_timestamp_uses_transcribed_data(self):
        chunks = [Document(page_content="ctx")]
        rag = self._make_rag_with_chunks(chunks)

        mock_model = MagicMock()
        mock_prompt = MagicMock()
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = MagicMock(content="150")
        mock_prompt.__or__ = MagicMock(return_value=mock_chain)

        transcribed_data = {"segments": [{"start_ms": 0, "text": "Hello"}]}
        result = rag.retrieve_from_db_with_start_timestamp(
            content="The opening scene",
            transcribed_data=transcribed_data,
            model=mock_model,
            prompt=mock_prompt,
        )
        assert result == "150"
        call_kwargs = mock_chain.invoke.call_args[0][0]
        assert "transcribed_data" in call_kwargs
        assert call_kwargs["content"] == "The opening scene"
