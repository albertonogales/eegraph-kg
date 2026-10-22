"""EDF → EEGraph → Knowledge Graph pipeline."""
from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings("ignore")

import networkx as nx
import numpy as np
import mne
from eegraph import Graph as EEG
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from eegraph_ext.kg import EEGraphKGExporter
from rdflib import ConjunctiveGraph


def build_kg_from_edf(
    edf_path: str,
    window_size: int = 60,
    threshold: float = 0.7,
    montage: str = "auto",
    output_turtle: str | None = None,
) -> tuple[ConjunctiveGraph, dict, list]:
    G = EEG()
    G.load_data(path=edf_path)

    # EEGraph derives node names by splitting channel labels on hyphens, so
    # bipolar channels sharing a pole (e.g. FP1-F7 and FP1-F3 both → FP1)
    # collapse onto the same node, producing self-loops and overwritten weights.
    # Replace hyphens with underscores before modelate so every channel keeps
    # a unique node name; translate back to original labels afterwards.
    original_ch_names = list(G.ch_names)
    G.ch_names = [c.replace("-", "_") for c in original_ch_names]
    # node_to_label maps the underscored node name EEGraph produces back to the
    # original bipolar label (e.g. "FP1_F7" → "FP1-F7").
    node_to_label = {safe.split()[-1]: orig
                     for safe, orig in zip(G.ch_names, original_ch_names)}
    assert len(node_to_label) == len(original_ch_names), \
        "channel names are not unique after hyphen→underscore renaming"

    graphs_dict, raw_matrices = G.modelate(
        window_size=window_size,
        connectivity="pearson_correlation",
        threshold=threshold,
    )

    # Compute per-window NaN pair counts from the raw connectivity matrix (A3g).
    # raw_matrices is an ndarray of shape (n_windows, n_ch, n_ch).
    nan_counts: dict[int, int] = {}
    try:
        if hasattr(raw_matrices, 'shape') and raw_matrices.ndim == 3:
            for k in range(raw_matrices.shape[0]):
                m = raw_matrices[k]
                iu = np.triu_indices_from(m, k=1)
                n = int(np.isnan(m[iu]).sum())
                if n > 0:
                    nan_counts[k] = n
    except Exception:
        nan_counts = {}

    # Validate: every window must have exactly the expected number of nodes
    # and no self-loops (which would indicate pole-collision was not fixed).
    for win_idx, g in graphs_dict.items():
        assert g.number_of_nodes() == len(original_ch_names), (
            f"Window {win_idx}: expected {len(original_ch_names)} nodes, "
            f"got {g.number_of_nodes()}"
        )
        assert nx.number_of_selfloops(g) == 0, (
            f"Window {win_idx}: self-loops detected — bipolar pole collision not resolved"
        )

    # Rename nodes in every graph back to original labels so the exporter
    # receives the canonical bipolar labels it needs for IRI and pole construction.
    graphs_dict = {
        win_idx: nx.relabel_nodes(g, node_to_label)
        for win_idx, g in graphs_dict.items()
    }

    exp = EEGraphKGExporter(
        graphs_dict=graphs_dict,
        ch_names=original_ch_names,
        connectivity="pearson_correlation",
        threshold=threshold,
        eeg_file=os.path.basename(edf_path),
        window_size=window_size,
        montage=montage,
        nan_counts=nan_counts,
    )
    cg = exp.build()
    if output_turtle:
        os.makedirs(os.path.dirname(os.path.abspath(output_turtle)), exist_ok=True)
        exp.to_turtle(output_turtle)
    return cg, graphs_dict, original_ch_names


def build_kg_from_raws(
    raw_paths: list[str],
    window_size: int = 30,
    threshold: float = 0.7,
    montage: str = "monopolar",
    output_turtle: str | None = None,
) -> tuple[ConjunctiveGraph, dict, list]:
    import tempfile
    raws = [mne.io.read_raw_edf(p, preload=True, verbose=False) for p in raw_paths]
    raw = mne.concatenate_raws(raws)
    raw.rename_channels({ch: ch.rstrip(".").upper() for ch in raw.ch_names})
    with tempfile.NamedTemporaryFile(suffix=".edf", delete=False) as tmp:
        tmp_path = tmp.name
    mne.export.export_raw(tmp_path, raw, fmt="edf", overwrite=True, verbose=False)
    try:
        cg, graphs_dict, ch_names = build_kg_from_edf(
            tmp_path, window_size, threshold, montage, output_turtle)
    finally:
        os.unlink(tmp_path)
    return cg, graphs_dict, ch_names
