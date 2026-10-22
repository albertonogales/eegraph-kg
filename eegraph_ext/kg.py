"""
EEG connectivity → Knowledge Graph exporter.

Converts windowed connectivity data to an RDF/Turtle knowledge graph using
established Semantic Web ontologies (SOSA, OWL-Time, PROV-O, SKOS, SIO,
Schema.org) and the eego: application ontology for electrode position identity.

Supports both monopolar (eego:Electrode / sosa:Sensor nodes) and bipolar
montages (eego:BipolarChannel nodes with eego:positivePole / eego:negativePole).

Designed for use with EEGraph output but accepts any windowed connectivity data
in the form of a dict mapping integer window indices to NetworkX weighted graphs
whose nodes are channel label strings and whose edges carry a ``weight``
attribute. See ``EEGKGExporter`` for the generic class and ``EEGraphKGExporter``
for the EEGraph-specific subclass with default provenance values.
"""

from __future__ import annotations

import datetime
import re
from typing import Dict, List, Optional

import numpy as np

import networkx as nx
from rdflib import (
    BNode, ConjunctiveGraph, Graph as RDFGraph,
    Literal, Namespace, URIRef
)
from rdflib.namespace import OWL, PROV, RDF, RDFS, SKOS, XSD

# ── Established namespaces ────────────────────────────────────────────────────
SOSA   = Namespace("http://www.w3.org/ns/sosa/")
TIME   = Namespace("http://www.w3.org/2006/time#")
SCHEMA = Namespace("https://schema.org/")
SIO    = Namespace("http://semanticscience.org/resource/")
EEGO   = Namespace("http://eegraph.org/ontology#")
EEGR   = Namespace("http://eegraph.org/resource/")

_SIO_X = SIO["SIO_000200"]
_SIO_Y = SIO["SIO_000201"]

# ── Measure metadata ──────────────────────────────────────────────────────────

_SINGLE_CHANNEL = {"power_spectrum", "spectral_entropy", "shannon_entropy"}
_DIRECTED       = {"dtf"}

_DEFAULTS: Dict[str, float] = {
    "pearson_correlation": 0.7, "cross_correlation": 0.5,
    "corr_cross_correlation": 0.1, "squared_coherence": 0.65,
    "imag_coherence": 0.4, "wpli": 0.45, "plv": 0.8,
    "pli": 0.1, "pli_bands": 0.1, "dtf": 0.3,
    "power_spectrum": 0.25, "spectral_entropy": 0.25, "shannon_entropy": 0.25,
}

_RULE: Dict[str, str] = {
    "pearson_correlation": "ValueAbove", "squared_coherence": "ValueAbove",
    "wpli": "ValueAbove", "plv": "ValueAbove", "pli": "ValueAbove",
    "pli_bands": "ValueAbove", "dtf": "ValueAbove",
    "cross_correlation": "MagnitudeAboveUndirected",
    "corr_cross_correlation": "MagnitudeAboveUndirected",
    "imag_coherence": "MagnitudeAboveUndirected",
    "power_spectrum": "TopFraction", "spectral_entropy": "TopFraction",
    "shannon_entropy": "TopFraction",
}

# Map EEGraph measure name → eego: ontology IRI local name
_MEASURE_IRI: Dict[str, str] = {
    "pearson_correlation":    "PearsonCorrelation",
    "cross_correlation":      "CrossCorrelation",
    "corr_cross_correlation": "CorrectedCrossCorrelation",
    "squared_coherence":      "SquaredCoherence",
    "imag_coherence":         "ImaginaryCoherence",
    "wpli":                   "WPLI",
    "plv":                    "PLV",
    "pli":                    "PLI",
    "pli_bands":              "PLIBands",
    "dtf":                    "DTF",
    "power_spectrum":         "PowerSpectrum",
    "spectral_entropy":       "SpectralEntropy",
    "shannon_entropy":        "ShannonEntropy",
}

# Map band name → eego: frequency band IRI local name
_BAND_IRI: Dict[str, str] = {
    "delta": "Delta", "theta": "Theta", "alpha": "Alpha",
    "beta": "Beta", "gamma": "Gamma",
}

# Electrode positions defined in the eego ontology (eego.ttl).
# Covers the 19 standard 10/20 positions (IEC 60601-2-26) plus OZ and four
# 10/10 extensions (AF3, AF4, FC5, FC6) used in the EEGMMIDB 64-channel montage.
_EEGO_ELECTRODES: set[str] = {
    "FP1", "FP2", "F7",  "F3",  "FZ",  "F4",  "F8",
    "T7",  "C3",  "CZ",  "C4",  "T8",
    "P7",  "P3",  "PZ",  "P4",  "P8",
    "O1",  "OZ",  "O2",
    "AF3", "AF4", "FC5", "FC6",
}

_SCALP_POS = {
    "FP1": (-0.18, 0.85), "FP2": (0.18, 0.85),
    "F7":  (-0.54, 0.55), "F3":  (-0.32, 0.55),
    "FZ":  (0.00, 0.60),  "F4":  (0.32, 0.55),
    "F8":  (0.54, 0.55),  "T7":  (-0.80, 0.00),
    "C3":  (-0.45, 0.00), "CZ":  (0.00, 0.00),
    "C4":  (0.45, 0.00),  "T8":  (0.80, 0.00),
    "P7":  (-0.54,-0.55), "P3":  (-0.32,-0.55),
    "PZ":  (0.00,-0.60),  "P4":  (0.32,-0.55),
    "P8":  (0.54,-0.55),  "O1":  (-0.18,-0.85),
    "OZ":  (0.00,-0.90),  "O2":  (0.18,-0.85),
    "AF3": (-0.28, 0.72), "AF4": (0.28, 0.72),
    "FC5": (-0.60, 0.30), "FC6": (0.60, 0.30),
}


def _eego_electrode_uri(label: str) -> Optional[URIRef]:
    """Return the eego ontology URI for a known electrode label (case-insensitive)."""
    key = label.upper()
    if key in _EEGO_ELECTRODES:
        return EEGO[f"Electrode_{key}"]
    return None


def _scalp_pos(label: str) -> Optional[tuple]:
    """Return (x, y) scalp position for an electrode label (case-insensitive)."""
    return _SCALP_POS.get(label.upper())


def _looks_bipolar(ch: str) -> bool:
    """Heuristic: True if ch looks like a bipolar differential channel (e.g. 'FP1-F7')."""
    return bool(re.match(r"^[A-Za-z0-9]+-[A-Za-z0-9]+$", ch))


def _bipolar_poles(ch: str) -> tuple[str, str]:
    """Split 'FP1-F7' → ('FP1', 'F7').

    MNE appends a numeric suffix to duplicate derivations (e.g. 'T8-P8-0',
    'T8-P8-1'); the suffix is part of the channel IRI but must be stripped
    when extracting the negative pole electrode label.
    """
    parts = ch.split("-")
    pos = parts[0].upper()
    # Strip a trailing all-digit token (MNE duplicate suffix) from the neg pole
    neg_raw = parts[1]
    neg = neg_raw.upper()
    return pos, neg


class EEGKGExporter:
    """Convert windowed EEG connectivity data to an RDF Knowledge Graph.

    Parameters
    ----------
    graphs_dict : dict[int, nx.Graph]
        Windowed connectivity data: integer window index → NetworkX undirected
        weighted graph. Each graph's nodes must be channel label strings and
        each edge must carry a ``weight`` attribute (float).
    ch_names : list[str]
        Ordered list of channel / electrode labels. Must cover all nodes
        present in any graph in ``graphs_dict``.
    connectivity : str
        Name of the connectivity measure (e.g. ``'pearson_correlation'``).
    threshold : float, optional
        Edge-weight threshold applied upstream. Stored as provenance metadata.
    bands : list[str], optional
        Frequency-band names if the windows are band-stratified
        (e.g. ``['delta', 'alpha']``). Pass ``None`` for broadband measures.
    eeg_file : str, optional
        Source EEG filename for provenance (e.g. ``'chb01_03.edf'``).
    window_size : int, optional
        Time-window duration in seconds.
    montage : str, optional
        ``'monopolar'``, ``'bipolar'``, or ``'auto'`` (default).
        ``'auto'`` infers the type from channel names: any name matching the
        pattern ``LABEL-LABEL`` (e.g. ``FP1-F7``) is treated as bipolar.
        Pass ``'monopolar'`` or ``'bipolar'`` explicitly when channel names
        do not follow this convention.
    tool_name : str, optional
        Name of the software tool that produced the connectivity data.
    tool_version : str, optional
        Version string of the tool.
    tool_url : str, optional
        Repository or homepage URL of the tool.
    """

    def __init__(
        self,
        graphs_dict: Dict[int, nx.Graph],
        ch_names: List[str],
        connectivity: str = "unknown",
        threshold: Optional[float] = None,
        bands: Optional[List] = None,
        eeg_file: str = "unknown.edf",
        window_size: int = 5,
        montage: str = "auto",
        tool_name: str = "unknown",
        tool_version: str = "unknown",
        tool_url: str = "https://example.org",
        nan_counts: Optional[Dict[int, int]] = None,
    ):
        if montage not in ("auto", "monopolar", "bipolar"):
            raise ValueError("montage must be 'auto', 'monopolar', or 'bipolar'")

        self.graphs_dict = graphs_dict
        self.ch_names = ch_names
        self.connectivity = connectivity
        self.bands = bands or []
        self.eeg_file = eeg_file
        self.window_size = window_size
        self.tool_name = tool_name
        self.tool_version = tool_version
        self.tool_url = tool_url
        self.nan_counts: Dict[int, int] = nan_counts or {}
        self._cg: Optional[ConjunctiveGraph] = None

        # Effective threshold: caller value if supplied, else measure default
        self.threshold: float = (
            threshold if threshold is not None
            else _DEFAULTS.get(connectivity, 0.3)
        )
        self._threshold_rule: Optional[str] = _RULE.get(connectivity)
        self._is_directed = connectivity in _DIRECTED
        self._is_single_channel = connectivity in _SINGLE_CHANNEL
        # eego: measure IRI (None for unknown measures)
        self._measure_uri: Optional[URIRef] = (
            EEGO[_MEASURE_IRI[connectivity]] if connectivity in _MEASURE_IRI else None
        )

        if montage == "auto":
            self._is_bipolar_montage = any(_looks_bipolar(ch) for ch in ch_names)
        else:
            self._is_bipolar_montage = (montage == "bipolar")

    # ── Public API ─────────────────────────────────────────────────────────────

    def build(self) -> ConjunctiveGraph:
        """Validate inputs and build the ConjunctiveGraph."""
        if self._is_single_channel:
            raise NotImplementedError(
                f"Single-channel measure '{self.connectivity}' is not yet supported by "
                "the KG exporter. Add the eego:NodeMeasurement export path in "
                "eegraph_ext/kg.py _add_windows() to implement it."
            )
        self._validate()
        cg = ConjunctiveGraph()
        for prefix, ns in [
            ("sosa", SOSA), ("time", TIME), ("schema", SCHEMA),
            ("sio", SIO), ("skos", SKOS),
            ("prov", PROV), ("owl", OWL), ("eego", EEGO), ("eegr", EEGR),
        ]:
            cg.bind(prefix, ns)

        self._add_ontology_import(cg)
        self._add_software_agent(cg)
        self._add_electrodes(cg)
        self._add_recording(cg)
        self._add_windows(cg)
        self._cg = cg
        return cg

    def to_turtle(self, path: str) -> None:
        """Serialise the KG to a TriG file (named-graph-aware superset of Turtle)."""
        if self._cg is None:
            self.build()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self._cg.serialize(format="trig"))

    def to_string(self, fmt: str = "trig") -> str:
        """Serialise the KG to a string."""
        if self._cg is None:
            self.build()
        return self._cg.serialize(format=fmt)

    # ── Validation ─────────────────────────────────────────────────────────────

    def _validate(self) -> None:
        ch_set = set(self.ch_names)
        for win_idx, G in self.graphs_dict.items():
            unknown = set(G.nodes) - ch_set
            if unknown:
                raise ValueError(
                    f"Window {win_idx}: graph nodes {sorted(unknown)} are not "
                    f"in ch_names. Pass the complete channel list to the constructor."
                )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _slug(self, *parts) -> str:
        return "_".join(str(p).replace(" ", "_").replace("/", "-") for p in parts)

    def _add_ontology_import(self, cg: ConjunctiveGraph):
        """Declare owl:imports so the KG is self-describing via the eego ontology IRI."""
        g = cg.get_context(EEGO["ontology"])
        ont_iri = URIRef("http://eegraph.org/ontology")
        g.add((ont_iri, RDF.type, OWL.Ontology))
        g.add((ont_iri, OWL.imports, URIRef("http://eegraph.org/ontology")))
        g.add((ont_iri, RDFS.label, Literal("EEGraph KG — ontology import declaration")))

    def _add_software_agent(self, cg: ConjunctiveGraph):
        g = cg.get_context(EEGO["provenance"])
        tool_slug = self._slug(self.tool_name)
        sw = EEGR[f"software/{tool_slug}"]
        g.add((sw, RDF.type, SCHEMA.SoftwareApplication))
        g.add((sw, RDF.type, PROV.SoftwareAgent))
        g.add((sw, SCHEMA.name,    Literal(self.tool_name)))
        g.add((sw, SCHEMA.version, Literal(self.tool_version)))
        g.add((sw, SCHEMA.url,     URIRef(self.tool_url)))
        self._sw_uri = sw

    def _add_electrodes(self, cg: ConjunctiveGraph):
        g = cg.get_context(EEGO["electrodes"])

        if self._is_bipolar_montage:
            poles: set[str] = set()
            for ch in self.ch_names:
                if _looks_bipolar(ch):
                    pos, neg = _bipolar_poles(ch)
                    poles.add(pos)
                    poles.add(neg)
                else:
                    poles.add(ch.upper())

            for pole in poles:
                e_uri = EEGR[f"electrode/{pole}"]
                g.add((e_uri, RDF.type, EEGO["Electrode"]))
                g.add((e_uri, RDFS.label, Literal(pole)))
                eego_uri = _eego_electrode_uri(pole)
                if eego_uri:
                    g.add((e_uri, SKOS.exactMatch, eego_uri))
                pos = _scalp_pos(pole)
                if pos:
                    x, y = pos
                    g.add((e_uri, EEGO["scalp2DX"], Literal(x, datatype=XSD.float)))
                    g.add((e_uri, EEGO["scalp2DY"], Literal(y, datatype=XSD.float)))
                    sio_node = BNode()
                    g.add((e_uri, SIO["SIO_000008"], sio_node))
                    g.add((sio_node, _SIO_X, Literal(x, datatype=XSD.float)))
                    g.add((sio_node, _SIO_Y, Literal(y, datatype=XSD.float)))

            for ch in self.ch_names:
                if _looks_bipolar(ch):
                    pos_pole, neg_pole = _bipolar_poles(ch)
                    ch_uri = EEGR[f"channel/{ch}"]
                    g.add((ch_uri, RDF.type, EEGO["BipolarChannel"]))
                    g.add((ch_uri, RDFS.label, Literal(ch)))
                    g.add((ch_uri, EEGO["positivePole"], EEGR[f"electrode/{pos_pole}"]))
                    g.add((ch_uri, EEGO["negativePole"], EEGR[f"electrode/{neg_pole}"]))
        else:
            for ch in self.ch_names:
                key = ch.upper()
                e_uri = EEGR[f"electrode/{ch}"]
                g.add((e_uri, RDF.type, EEGO["Electrode"]))
                g.add((e_uri, RDF.type, SOSA.Sensor))
                g.add((e_uri, RDFS.label, Literal(ch)))
                eego_uri = _eego_electrode_uri(key)
                if eego_uri:
                    g.add((e_uri, SKOS.exactMatch, eego_uri))
                sp = _scalp_pos(key)
                if sp:
                    x, y = sp
                    g.add((e_uri, EEGO["scalp2DX"], Literal(x, datatype=XSD.float)))
                    g.add((e_uri, EEGO["scalp2DY"], Literal(y, datatype=XSD.float)))
                    sio_node = BNode()
                    g.add((e_uri, SIO["SIO_000008"], sio_node))
                    g.add((sio_node, _SIO_X, Literal(x, datatype=XSD.float)))
                    g.add((sio_node, _SIO_Y, Literal(y, datatype=XSD.float)))

    def _add_recording(self, cg: ConjunctiveGraph):
        g = cg.get_context(EEGO["provenance"])
        rec = EEGR[f"recording/{self._slug(self.eeg_file)}"]
        g.add((rec, RDF.type, SOSA.ObservationCollection))
        g.add((rec, RDF.type, PROV.Entity))
        g.add((rec, RDFS.label, Literal(self.eeg_file)))
        g.add((rec, PROV.wasAttributedTo, self._sw_uri))
        now = datetime.datetime.utcnow().isoformat()
        g.add((rec, PROV.generatedAtTime, Literal(now, datatype=XSD.dateTime)))

        activity = EEGR[f"activity/{self._slug(self.eeg_file, self.connectivity)}"]
        g.add((activity, RDF.type, PROV.Activity))
        g.add((activity, RDFS.label, Literal(f"{self.connectivity} analysis")))
        g.add((activity, PROV.wasAssociatedWith, self._sw_uri))
        g.add((activity, PROV.used, rec))
        if self._measure_uri is not None:
            g.add((activity, EEGO["connectivityMeasure"], self._measure_uri))
        else:
            g.add((activity, EEGO["connectivityMeasure"], Literal(self.connectivity)))
        g.add((activity, EEGO["threshold"], Literal(self.threshold, datatype=XSD.decimal)))
        if self._threshold_rule:
            g.add((activity, EEGO["thresholdRule"], EEGO[self._threshold_rule]))
        self._recording_uri = rec
        self._activity_uri = activity

    def _add_windows(self, cg: ConjunctiveGraph):
        now = datetime.datetime.utcnow().isoformat()
        _CANONICAL = ["delta", "theta", "alpha", "beta", "gamma"]
        active_bands = [b for b in _CANONICAL
                        if b in [x.lower() if isinstance(x, str) else "" for x in self.bands]]
        nb = len(active_bands)

        for win_idx, G in self.graphs_dict.items():
            # Decode temporal window index and frequency band from EEGraph graph key
            if nb:
                window_index = win_idx // nb
                band_name = active_bands[win_idx % nb]
            else:
                window_index = win_idx
                band_name = None

            win_uri  = EEGR[f"window/{self._slug(self.eeg_file, window_index)}"]
            ctx_name = EEGO[f"window/{self._slug(self.eeg_file, win_idx)}"]
            g = cg.get_context(ctx_name)

            g.add((win_uri, RDF.type,       EEGO["TimeWindow"]))
            g.add((win_uri, RDF.type,       TIME.Interval))
            g.add((win_uri, RDFS.label,     Literal(f"Window {window_index}")))
            start_sec = window_index * self.window_size
            g.add((win_uri, TIME.hasBeginning, Literal(start_sec, datatype=XSD.float)))
            g.add((win_uri, TIME.hasDuration,  Literal(self.window_size, datatype=XSD.float)))
            if band_name:
                band_uri = EEGO[_BAND_IRI[band_name]] if band_name in _BAND_IRI else None
                g.add((win_uri, EEGO["frequencyBand"],
                       band_uri if band_uri else Literal(band_name)))

            # NaN pair count (A3g)
            nan_n = self.nan_counts.get(win_idx, 0)
            if nan_n > 0:
                g.add((win_uri, EEGO["nanPairCount"], Literal(nan_n, datatype=XSD.integer)))

            for u, v, data in G.edges(data=True):
                weight = float(data.get("weight", 0.0))
                edge_id = self._slug(self.eeg_file, win_idx, u, v)
                edge_uri = EEGR[f"edge/{edge_id}"]

                if self._is_bipolar_montage:
                    u_uri = EEGR[f"channel/{u}"]
                    v_uri = EEGR[f"channel/{v}"]
                else:
                    u_uri = EEGR[f"electrode/{u}"]
                    v_uri = EEGR[f"electrode/{v}"]

                g.add((edge_uri, RDF.type,                EEGO["ConnectivityEdge"]))
                g.add((edge_uri, RDF.type,                PROV.Entity))
                g.add((edge_uri, EEGO["sourceElectrode"], u_uri))
                g.add((edge_uri, EEGO["targetElectrode"], v_uri))
                g.add((edge_uri, EEGO["weight"],
                       Literal(weight, datatype=XSD.decimal)))
                if self._measure_uri is not None:
                    g.add((edge_uri, EEGO["connectivityMeasure"], self._measure_uri))
                else:
                    g.add((edge_uri, EEGO["connectivityMeasure"],
                           Literal(self.connectivity)))
                g.add((edge_uri, EEGO["inWindow"],     win_uri))
                g.add((edge_uri, PROV.wasGeneratedBy,  self._activity_uri))
                g.add((edge_uri, PROV.generatedAtTime, Literal(now, datatype=XSD.dateTime)))
                if band_name:
                    band_uri = EEGO[_BAND_IRI[band_name]] if band_name in _BAND_IRI else None
                    g.add((edge_uri, EEGO["frequencyBand"],
                           band_uri if band_uri else Literal(band_name)))

                # RDF-star annotation; falls back to reification for older stores.
                # For directed measures use eego:directedConnection (not symmetric).
                conn_pred = (EEGO["directedConnection"] if self._is_directed
                             else EEGO["connectedTo"])
                base_triple = (u_uri, conn_pred, v_uri)
                g.add(base_triple)
                try:
                    g.add((base_triple, EEGO["weight"],  Literal(weight, datatype=XSD.decimal)))
                    g.add((base_triple, EEGO["inWindow"], win_uri))
                    if band_name:
                        band_uri = EEGO[_BAND_IRI[band_name]] if band_name in _BAND_IRI else None
                        g.add((base_triple, EEGO["frequencyBand"],
                               band_uri if band_uri else Literal(band_name)))
                except (TypeError, AssertionError):
                    stmt = BNode()
                    g.add((stmt, RDF.type,      RDF.Statement))
                    g.add((stmt, RDF.subject,   u_uri))
                    g.add((stmt, RDF.predicate, conn_pred))
                    g.add((stmt, RDF.object,    v_uri))
                    g.add((stmt, EEGO["weight"],  Literal(weight, datatype=XSD.decimal)))
                    g.add((stmt, EEGO["inWindow"], win_uri))


class EEGraphKGExporter(EEGKGExporter):
    """EEGKGExporter pre-configured with EEGraph provenance metadata."""

    def __init__(
        self,
        graphs_dict: Dict[int, nx.Graph],
        ch_names: List[str],
        connectivity: str = "unknown",
        threshold: Optional[float] = None,
        bands: Optional[List] = None,
        eeg_file: str = "unknown.edf",
        window_size: int = 5,
        montage: str = "auto",
        nan_counts: Optional[Dict[int, int]] = None,
    ):
        super().__init__(
            graphs_dict=graphs_dict,
            ch_names=ch_names,
            connectivity=connectivity,
            threshold=threshold,
            bands=bands,
            eeg_file=eeg_file,
            window_size=window_size,
            montage=montage,
            tool_name="EEGraph",
            tool_version="0.1.17",
            tool_url="https://github.com/ufvceiec/EEGRAPH",
            nan_counts=nan_counts,
        )


def export_kg(
    graphs_dict: Dict[int, nx.Graph],
    ch_names: List[str],
    connectivity: str = "unknown",
    threshold: Optional[float] = None,
    bands: Optional[List] = None,
    eeg_file: str = "unknown.edf",
    window_size: int = 5,
    output_path: Optional[str] = None,
    montage: str = "auto",
    tool_name: str = "EEGraph",
    tool_version: str = "0.1.17",
    tool_url: str = "https://github.com/ufvceiec/EEGRAPH",
    nan_counts: Optional[Dict[int, int]] = None,
) -> EEGKGExporter:
    """Build and optionally save a KG from windowed EEG connectivity data.

    Returns the populated exporter so callers can access the ConjunctiveGraph
    or serialise to additional formats.
    """
    exp = EEGKGExporter(
        graphs_dict=graphs_dict,
        ch_names=ch_names,
        connectivity=connectivity,
        threshold=threshold,
        bands=bands,
        eeg_file=eeg_file,
        window_size=window_size,
        montage=montage,
        tool_name=tool_name,
        tool_version=tool_version,
        tool_url=tool_url,
        nan_counts=nan_counts,
    )
    exp.build()
    if output_path:
        exp.to_turtle(output_path)
    return exp
