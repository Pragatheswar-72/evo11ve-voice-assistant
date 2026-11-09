"""
Simple retrieval over the knowledge base.

The KB is one markdown file split into sections (one chunk per "## " heading).
Since the KB is small, TF-IDF + cosine similarity is enough and keeps the
deployment light (no torch / embedding model to download).
"""

import re
from pathlib import Path

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def tokenize(text: str) -> list[str]:
    # lowercase, drop stop words and do a very basic plural strip ("mentors" -> "mentor")
    words = re.findall(r"[a-z0-9]+", text.lower())
    tokens = []
    for w in words:
        if w in ENGLISH_STOP_WORDS:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        tokens.append(w)
    return tokens


class KnowledgeBase:
    def __init__(self, md_path: str | Path):
        text = Path(md_path).read_text(encoding="utf-8")
        self.chunks = self._split_sections(text)

        self.vectorizer = TfidfVectorizer(tokenizer=tokenize, token_pattern=None, ngram_range=(1, 2))
        self.matrix = self.vectorizer.fit_transform(self.chunks)

    @staticmethod
    def _split_sections(text: str) -> list[str]:
        chunks = []
        for part in text.split("\n## "):
            part = part.strip()
            # skip the file title / source line at the top
            if not part or part.startswith("# "):
                continue
            chunks.append("## " + part)
        return chunks

    def search(self, query: str, k: int = 4) -> list[str]:
        """Return the k most relevant sections for the query."""
        q_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(q_vec, self.matrix)[0]
        best = scores.argsort()[::-1][:k]

        results = [self.chunks[i] for i in best if scores[i] > 0]

        # greetings like "hi" won't match anything - fall back to the overview
        if not results:
            results = [c for c in self.chunks if c.startswith("## Program Overview")]
        return results
