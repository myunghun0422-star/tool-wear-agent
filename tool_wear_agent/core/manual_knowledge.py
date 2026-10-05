from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import fitz  # PyMuPDF


@dataclass
class ManualGuidance:
    id: str
    source: str
    source_type: str
    location: str
    guidance: str
    decision_use: str
    score: int = 0

    def to_dict(self):
        return asdict(self)


class ManualKnowledgeBase:
    """원본 제조사 PDF를 런타임에 직접 읽어 판단 근거를 제공하는 로컬 검색 계층.

    제조사 PDF의 원문을 실제로 읽고, 설정된 검색어가 확인된 경우에만 해당 근거를
    '원문 확인 완료'로 반환한다. 화면에는 사용자가 이해하기 쉬운 한국어 설명을
    제공하되, 내부 결과에는 실제로 추출한 원문도 함께 보존한다.

    한 PDF 또는 한 페이지를 읽지 못하더라도 실시간 API 전체가 중단되지 않도록
    파일별/페이지별 오류를 격리한다.
    """

    def __init__(self, knowledge_path: Path):
        self.path = Path(knowledge_path)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.entries = payload.get("entries", [])
        self.manual_dir = self.path.parent.parent / "manuals"
        self._docs: dict[str, fitz.Document] = {}
        self._page_cache: dict[tuple[str, int], str] = {}
        self._load_errors: dict[str, str] = {}

        for entry in self.entries:
            src = entry.get("source", "")
            if not src.lower().endswith(".pdf") or src in self._docs or src in self._load_errors:
                continue
            pdf_path = self.manual_dir / src
            if not pdf_path.exists():
                self._load_errors[src] = f"원본 PDF 파일 없음: {pdf_path.name}"
                continue
            try:
                doc = fitz.open(str(pdf_path))
                if doc.needs_pass:
                    self._load_errors[src] = "암호가 필요한 PDF라 본문을 읽을 수 없습니다."
                    doc.close()
                    continue
                self._docs[src] = doc
            except Exception as exc:
                self._load_errors[src] = f"PDF 열기 실패: {type(exc).__name__}: {exc}"

    def __del__(self):
        for doc in getattr(self, "_docs", {}).values():
            try:
                doc.close()
            except Exception:
                pass

    @staticmethod
    def _clean_text(text: str) -> str:
        text = text.replace("\x00", " ")
        return re.sub(r"\s+", " ", text).strip()

    def _page_text(self, source: str, page_number: int) -> str:
        key = (source, int(page_number))
        if key in self._page_cache:
            return self._page_cache[key]

        doc = self._docs.get(source)
        if doc is None or page_number < 1 or page_number > doc.page_count:
            return ""
        try:
            page = doc.load_page(page_number - 1)
            text = self._clean_text(page.get_text("text") or "")
            self._page_cache[key] = text
            return text
        except Exception as exc:
            self._load_errors[source] = f"PDF 본문 추출 실패: {type(exc).__name__}: {exc}"
            return ""

    @staticmethod
    def _sentences(text: str) -> list[str]:
        parts = re.split(r"(?<=[.!?])\s+|\s+[•]\s+", text)
        return [p.strip(" •") for p in parts if len(p.strip()) >= 25]

    def _best_excerpt(self, text: str, terms: list[str], max_chars: int = 680) -> tuple[str, int]:
        terms_l = [t.lower() for t in terms if t]
        ranked: list[tuple[int, int, str]] = []
        for i, sentence in enumerate(self._sentences(text)):
            low = sentence.lower()
            phrase_hits = sum(4 for term in terms_l if term in low)
            token_hits = sum(
                1
                for token in {w for term in terms_l for w in term.split()}
                if len(token) >= 4 and token in low
            )
            score = phrase_hits + token_hits
            if score > 0:
                ranked.append((score, -i, sentence))

        if not ranked:
            return "", 0

        ranked.sort(reverse=True)
        picked: list[str] = []
        total = 0
        for _, _, sentence in ranked[:4]:
            if sentence in picked:
                continue
            if total + len(sentence) + 1 > max_chars and picked:
                continue
            picked.append(sentence)
            total += len(sentence) + 1
            if total >= max_chars * 0.72:
                break
        return " ".join(picked)[:max_chars].strip(), ranked[0][0]

    def _search_pdf_pages(self, source: str, terms: list[str], preferred_pages: list[int]) -> tuple[int, str, int] | None:
        doc = self._docs.get(source)
        if doc is None:
            return None

        pages = [p for p in preferred_pages if 1 <= p <= doc.page_count]
        if not pages:
            pages = list(range(1, doc.page_count + 1))

        best: tuple[int, int, str] | None = None
        for page in pages:
            text = self._page_text(source, page)
            if not text:
                continue
            excerpt, score = self._best_excerpt(text, terms)
            if score <= 0:
                continue
            candidate = (score, page, excerpt)
            if best is None or candidate[0] > best[0]:
                best = candidate

        # 설정된 페이지에서 찾지 못한 경우 전체 문서를 한 번 더 검색한다.
        if best is None and len(pages) < doc.page_count:
            for page in range(1, doc.page_count + 1):
                text = self._page_text(source, page)
                if not text:
                    continue
                excerpt, score = self._best_excerpt(text, terms)
                if score <= 0:
                    continue
                candidate = (score, page, excerpt)
                if best is None or candidate[0] > best[0]:
                    best = candidate

        return best

    def _pdf_guidance(self, entry: dict) -> dict | None:
        source = entry.get("source", "")
        if source not in self._docs:
            return None

        terms = entry.get("query_terms", []) or entry.get("tags", [])
        preferred_pages = [int(p) for p in entry.get("preferred_pages", [])]
        best = self._search_pdf_pages(source, terms, preferred_pages)
        if best is None:
            return None

        score, page, excerpt = best
        guidance_ko = (entry.get("guidance_ko") or entry.get("decision_use") or "").strip()
        return {
            "id": entry.get("id", ""),
            "source": source,
            "display_name": entry.get("display_name") or source,
            "source_type": entry.get("source_type", "제조사 원본 매뉴얼"),
            "location": f"원본 PDF p.{page}",
            "guidance": guidance_ko,
            "guidance_ko": guidance_ko,
            "decision_use": entry.get("decision_use", ""),
            "score": int(score),
            "retrieval_mode": "ORIGINAL_PDF",
            "verified_from_original": True,
            "page": page,
            "query_terms": terms,
        }

    def _resolve_entry(self, entry: dict) -> dict | None:
        source = entry.get("source", "")
        if source.lower().endswith(".pdf"):
            return self._pdf_guidance(entry)

        # 프로젝트 내부 운영 규칙은 제조사 원문과 구분해 사용한다.
        item = dict(entry)
        item["display_name"] = entry.get("display_name") or "운영 판단 규칙"
        item["guidance_ko"] = entry.get("guidance", "")
        item["retrieval_mode"] = "PROJECT_RULE"
        item["verified_from_original"] = False
        return item

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        words = {w.strip(".,:;()[]").lower() for w in query.split() if len(w.strip()) >= 2}
        ranked = []
        for entry in self.entries:
            haystack = " ".join([
                entry.get("id", ""),
                entry.get("source", ""),
                entry.get("decision_use", ""),
                " ".join(entry.get("tags", [])),
                " ".join(entry.get("query_terms", [])),
            ]).lower()
            score = sum(3 for tag in entry.get("tags", []) if tag.lower() in query.lower())
            score += sum(1 for word in words if word in haystack)
            if score <= 0:
                continue
            resolved = self._resolve_entry(entry)
            if resolved:
                resolved["score"] = max(int(resolved.get("score", 0)), score)
                ranked.append(resolved)
        ranked.sort(key=lambda x: (-x.get("score", 0), x.get("id", "")))
        return ranked[:top_k]

    def by_ids(self, ids: list[str]) -> list[dict]:
        wanted = list(dict.fromkeys(ids))
        index = {x.get("id"): x for x in self.entries}
        resolved = []
        for item_id in wanted:
            entry = index.get(item_id)
            if not entry:
                continue
            item = self._resolve_entry(entry)
            if item:
                resolved.append(item)
        return resolved

    def originals_verified(self, ids: list[str]) -> bool:
        """요청한 제조사 PDF 근거가 실제 원문에서 확인됐는지 반환한다."""
        items = self.by_ids(ids)
        by_id = {item.get("id"): item for item in items}
        for item_id in ids:
            entry = next((e for e in self.entries if e.get("id") == item_id), None)
            if not entry or not str(entry.get("source", "")).lower().endswith(".pdf"):
                continue
            item = by_id.get(item_id)
            if not item or not item.get("verified_from_original"):
                return False
        return True

    def source_summary(self) -> list[dict]:
        seen = {}
        for e in self.entries:
            source = e.get("source", "")
            if source in seen:
                continue
            is_pdf = source.lower().endswith(".pdf")
            seen[source] = {
                "source": source,
                "display_name": e.get("display_name") or source,
                "type": e.get("source_type", ""),
                "mode": "ORIGINAL_PDF" if is_pdf else "PROJECT_RULE",
                "available": source in self._docs if is_pdf else (self.manual_dir / source).exists(),
                "error": self._load_errors.get(source),
            }
        return list(seen.values())
