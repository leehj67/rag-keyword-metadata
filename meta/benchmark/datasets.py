"""
BEIR, TREC, RepliQA 데이터셋 로더
- beir 패키지 사용 시: GenericDataLoader (권장)
- fallback: URL 다운로드 또는 HuggingFace
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Dict, Tuple, Optional


BEIR_BASE = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets"
BEIR_DATASETS = {
    "scifact": "scifact.zip",
    "nfcorpus": "nfcorpus.zip",
    "fiqa": "fiqa.zip",
    "arguana": "arguana.zip",
    "trec-covid": "trec-covid.zip",
    "dbpedia-entity": "dbpedia-entity.zip",
    "fever": "fever.zip",
    "climate-fever": "climate-fever.zip",
    "quora": "quora.zip",
}

HF_BEIR_MAP = {
    "scifact": "BeIR/scifact",
    "nfcorpus": "BeIR/nfcorpus",
    "fiqa": "BeIR/fiqa",
    "arguana": "BeIR/arguana",
    "trec-covid": "BeIR/trec-covid",
}


def _download_beir(dataset: str, data_dir: Path) -> Path:
    """BEIR 데이터셋 다운로드 (URL 실패 시 HuggingFace 사용)"""
    if dataset not in BEIR_DATASETS:
        raise ValueError(f"지원 데이터셋: {list(BEIR_DATASETS.keys())}")
    data_dir.mkdir(parents=True, exist_ok=True)
    extract_path = data_dir / dataset
    zip_name = BEIR_DATASETS[dataset]
    zip_path = data_dir / zip_name
    if not zip_path.exists():
        try:
            import urllib.request
            import ssl
            url = f"{BEIR_BASE}/{zip_name}"
            print(f"[BEIR] 다운로드: {url}")
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(url, context=ctx) as r:
                zip_path.write_bytes(r.read())
        except Exception as e:
            print(f"[BEIR] URL 다운로드 실패: {e}")
            zip_path = None
    if zip_path and zip_path.exists():
        if not extract_path.exists():
            print(f"[BEIR] 압축 해제: {zip_path}")
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(data_dir)
        return extract_path
    return extract_path


def _load_beir_from_hf(dataset: str, split: str) -> Tuple[Dict, Dict, Dict]:
    """HuggingFace에서 BEIR 로드 (BeIR/scifact 등)"""
    try:
        from datasets import load_dataset
    except ImportError:
        raise ImportError("datasets 필요: pip install datasets")
    hf_name = HF_BEIR_MAP.get(dataset)
    if not hf_name:
        raise ValueError(f"HuggingFace BEIR 미지원: {dataset}")

    corpus = {}
    try:
        corpus_ds = load_dataset(hf_name, "corpus", trust_remote_code=True)
        if isinstance(corpus_ds, dict):
            corpus_split = corpus_ds.get("corpus", corpus_ds)
        else:
            corpus_split = corpus_ds
        for row in corpus_split:
            doc_id = str(row.get("_id", row.get("id", "")))
            corpus[doc_id] = {
                "title": row.get("title", ""),
                "text": row.get("text", ""),
            }
    except Exception as e:
        print(f"[HF] corpus 로드 실패: {e}")
        raise

    queries = {}
    try:
        queries_ds = load_dataset(hf_name, "queries", trust_remote_code=True)
        if isinstance(queries_ds, dict):
            q_split = list(queries_ds.values())[0]
        else:
            q_split = queries_ds
        for row in q_split:
            qid = str(row.get("_id", row.get("id", "")))
            queries[qid] = row.get("text", row.get("query", ""))
    except Exception as e:
        print(f"[HF] queries 로드 실패: {e}")
        raise

    qrels = {}
    try:
        qrels_ds = load_dataset(hf_name, "qrels", trust_remote_code=True)
        if isinstance(qrels_ds, dict):
            qr_split = qrels_ds.get(split, list(qrels_ds.values())[0])
        else:
            qr_split = qrels_ds
        for row in qr_split:
            qid = str(row.get("query-id", row.get("query_id", row.get("query-id", ""))))
            doc_id = str(row.get("corpus-id", row.get("corpus_id", row.get("corpus-id", ""))))
            rel = int(row.get("score", row.get("relevance", 1)))
            if qid not in qrels:
                qrels[qid] = {}
            qrels[qid][doc_id] = rel
        queries = {qid: queries[qid] for qid in qrels if qid in queries}
    except Exception as e:
        print(f"[HF] qrels 로드 실패: {e}")
        raise

    return corpus, queries, qrels


def load_beir_dataset(
    dataset: str,
    split: str = "test",
    data_dir: Optional[Path] = None,
) -> Tuple[Dict, Dict, Dict]:
    """
    BEIR 형식 로드: corpus, queries, qrels
    1) beir 패키지 2) URL 다운로드 3) HuggingFace 순으로 시도
    """
    if data_dir is None:
        data_dir = Path(__file__).parent / "data"
    data_dir = Path(data_dir)

    try:
        from beir import util
        from beir.datasets.data_loader import GenericDataLoader
        url = f"https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/{dataset}.zip"
        data_path = util.download_and_unzip(url, str(data_dir))
        corpus, queries, qrels = GenericDataLoader(data_folder=data_path).load(split=split)
        return corpus, queries, qrels
    except ImportError:
        pass
    except Exception as e:
        print(f"[BEIR] beir 패키지 로드 실패: {e}")

    if dataset in HF_BEIR_MAP:
        try:
            return _load_beir_from_hf(dataset, split)
        except Exception as e:
            print(f"[BEIR] HuggingFace 로드 실패: {e}")

    if data_dir is None:
        data_dir = Path(__file__).parent / "data"
    data_path = _download_beir(dataset, data_dir)

    corpus = {}
    corpus_file = data_path / "corpus.jsonl"
    if corpus_file.exists():
        with open(corpus_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                obj = json.loads(line)
                doc_id = str(obj.get("_id", obj.get("id", "")))
                corpus[doc_id] = {
                    "title": obj.get("title", ""),
                    "text": obj.get("text", ""),
                }

    if not corpus and dataset in HF_BEIR_MAP:
        return _load_beir_from_hf(dataset, split)

    queries = {}
    query_file = data_path / "queries.jsonl"
    if query_file.exists():
        with open(query_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                obj = json.loads(line)
                qid = str(obj.get("_id", obj.get("id", "")))
                queries[qid] = obj.get("text", obj.get("query", ""))

    qrels = {}
    qrels_path = data_path / "qrels" / f"{split}.tsv"
    if qrels_path.exists():
        import csv
        with open(qrels_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
            next(reader, None)
            for row in reader:
                if len(row) >= 3:
                    qid, doc_id, rel = row[0], row[1], int(row[2])
                    if qid not in qrels:
                        qrels[qid] = {}
                    qrels[qid][doc_id] = rel
        queries = {qid: queries[qid] for qid in qrels if qid in queries}

    return corpus, queries, qrels


def load_repliqa_dataset(
    split: str = "repliqa_0",
    data_dir: Optional[Path] = None,
) -> Tuple[Dict, Dict, Dict]:
    """
    RepliQA (HuggingFace) 로드
    Topic Retrieval: query=question, retrieve document
    """
    try:
        from datasets import load_dataset
    except ImportError:
        raise ImportError("datasets 필요: pip install datasets")

    ds = load_dataset("ServiceNow/repliqa", split=split)
    corpus = {}
    queries = {}
    qrels = {}

    for row in ds:
        doc_id = str(row.get("document_id", ""))
        if doc_id and doc_id not in corpus:
            corpus[doc_id] = {
                "title": "",
                "text": row.get("document_extracted", ""),
            }
        qid = str(row.get("question_id", ""))
        if qid:
            queries[qid] = row.get("question", "")
            if row.get("answer") != "UNANSWERABLE":
                qrels[qid] = {doc_id: 1}

    return corpus, queries, qrels
