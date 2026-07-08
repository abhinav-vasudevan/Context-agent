import re
from typing import List

class RecursiveCharacterChunker:
    """
    Splits large texts into manageable chunks while preserving paragraph/sentence boundaries.
    Defaults to 8000 characters per chunk, simulating a context window boundary.
    """
    
    def __init__(self, chunk_size: int = 8000, overlap: int = 400):
        self.chunk_size = chunk_size
        self.overlap = overlap
        
    def chunk_text(self, text: str) -> List[str]:
        """
        Recursively chunks the text. Falls back from double newlines -> single newlines -> spaces.
        """
        if not text:
            return []
            
        return self._split(text, self.chunk_size, self.overlap)
        
    def _split(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        if len(text) <= chunk_size:
            return [text]
            
        # Try to split by paragraph
        paragraphs = re.split(r'\n\s*\n', text)
        if len(paragraphs) > 1 and max(len(p) for p in paragraphs) <= chunk_size:
            return self._merge_splits(paragraphs, "\n\n", chunk_size, overlap)
            
        # Try to split by single newline
        lines = text.split('\n')
        if len(lines) > 1 and max(len(l) for l in lines) <= chunk_size:
            return self._merge_splits(lines, "\n", chunk_size, overlap)
            
        # Try to split by sentences (rudimentary)
        sentences = re.split(r'(?<=[.!?])\s+', text)
        if len(sentences) > 1 and max(len(s) for s in sentences) <= chunk_size:
            return self._merge_splits(sentences, " ", chunk_size, overlap)
            
        # Hard fallback: force split by characters
        return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size - overlap)]
        
    def _merge_splits(self, splits: List[str], separator: str, chunk_size: int, overlap: int) -> List[str]:
        chunks = []
        current_chunk = []
        current_len = 0
        
        for split in splits:
            split_len = len(split) + (len(separator) if current_chunk else 0)
            
            if current_len + split_len > chunk_size and current_chunk:
                chunks.append(separator.join(current_chunk))
                
                # Setup next chunk with overlap
                overlap_len = 0
                overlap_chunk = []
                for s in reversed(current_chunk):
                    if overlap_len + len(s) + len(separator) <= overlap:
                        overlap_chunk.insert(0, s)
                        overlap_len += len(s) + len(separator)
                    else:
                        break
                        
                current_chunk = overlap_chunk
                current_len = overlap_len
                
            current_chunk.append(split)
            current_len += split_len
            
        if current_chunk:
            chunks.append(separator.join(current_chunk))
            
        return chunks
