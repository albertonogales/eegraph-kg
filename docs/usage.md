# Usage Guide

## Prerequisites

- Python 3.9+
- EEGraph installed (`pip install eegraph`)
- EDF files from CHB-MIT or EEGMMIDB (or your own data)

## Installation

```bash
git clone https://github.com/albertonogales/eegraph-kg-exporter.git
cd eegraph-kg-exporter
pip install -r requirements.txt
```

## Pipeline overview

```
EDF file(s)
    │
    ▼
EEGraph (connectivity computation)
    │  windowed NetworkX graphs with Pearson r weights
    ▼
EEGraphKGExporter (kg.py)
    │  RDF triples: sensors, observations, time windows, provenance
    ▼
.ttl file (TriG / named graphs, one graph per time window)
```

## Case 1 — Single EDF file

```python
from kg_pipeline import build_kg_from_edf

kg, windows, channels = build_kg_from_edf(
    edf_path="data/chb01_01.edf",
    window_size=60,       # seconds
    threshold=0.7,        # keep edges where |Pearson r| > 0.7
    montage="auto",       # "auto" | "monopolar" | "bipolar"
    output_turtle="kg/chb01_ctrl.ttl"
)
```

**Output**: a TriG file where each named graph is one time window  
(IRI: `eego:window/<filename>_<window_index>`).

## Case 2 — MNE-cached recordings (EEGMMIDB)

```python
from kg_pipeline import build_kg_from_raws

# Resting state (runs 1 and 2)
kg_rest = build_kg_from_raws(
    subject=1, runs=[1, 2],
    window_size=60, threshold=0.7,
    output_turtle="kg/S001_rest.ttl"
)

# Motor imagery task (runs 4, 8, 12)
kg_task = build_kg_from_raws(
    subject=1, runs=[4, 8, 12],
    window_size=60, threshold=0.7,
    output_turtle="kg/S001_task.ttl"
)
```

MNE downloads the recordings automatically on first run to `~/mne_data/`.

## Case 3 — Custom connectivity data

Use `EEGKGExporter` directly if you already have windowed graphs:

```python
from eegraph_ext.kg import EEGKGExporter
import networkx as nx

# windows_dict: {0: nx.Graph, 1: nx.Graph, ...}
# Each graph's nodes are channel labels; edges carry a "weight" attribute.
exporter = EEGKGExporter(
    windows_dict=windows_dict,
    edf_filename="my_recording.edf",
    sampling_rate=256,
    window_size=60,
    threshold=0.7,
    threshold_rule="ValueAbove",   # | "MagnitudeAboveUndirected" | "TopFraction"
    connectivity_measure="PearsonCorrelation",
)
kg = exporter.build()
kg.serialize("my_kg.ttl", format="trig")
```

## Querying the KG

### Load locally

```python
from rdflib import Dataset

ds = Dataset()
ds.parse("kg/chb01_ctrl.ttl", format="trig")

# All connectivity values above threshold
q = """
PREFIX eego: <http://eegraph.org/ontology#>
PREFIX sosa: <http://www.w3.org/ns/sosa/>

SELECT ?source ?target ?value WHERE {
  ?obs a eego:NodeMeasurement ;
       eego:sourceNode ?source ;
       eego:targetNode ?target ;
       sosa:hasSimpleResult ?value .
}
ORDER BY DESC(?value)
LIMIT 20
"""
for row in ds.query(q):
    print(row)
```

### Query the live SPARQL endpoint

Endpoint: **https://triplydb.com/AlbertoNogalesMoyano/Knowledge-Graph-EEG/sparql**

Example — count triples per connectivity measure:

```sparql
PREFIX eego: <http://eegraph.org/ontology#>

SELECT ?measure (COUNT(*) AS ?n) WHERE {
  ?act eego:connectivityMeasure ?measure .
}
GROUP BY ?measure
```

## Output format

Each `.ttl` file is a **TriG** document (named graphs). Structure:

| Named graph | Contents |
|---|---|
| `eego:ontology` | `owl:imports` declaration |
| `eego:provenance` | `prov:Activity` with parameters and software agent |
| `eego:electrodes` | One `sosa:Sensor` (or `eego:BipolarChannel`) per channel |
| `eego:window/<file>_<N>` | Connectivity observations for window N |

## Connectivity measures supported

| IRI | Name | Scope | Symmetry |
|---|---|---|---|
| `eego:PearsonCorrelation` | Pearson r | Pairwise | Symmetric |
| `eego:PLV` | Phase Locking Value | Pairwise | Symmetric |
| `eego:PLI` | Phase Lag Index | Pairwise | Antisymmetric |
| `eego:WPLI` | Weighted PLI | Pairwise | Antisymmetric |
| `eego:Coherence` | Coherence | Pairwise | Symmetric |
| `eego:DTC` | Directed Transfer Coherence | Pairwise | Directed |
| `eego:DTF` | Directed Transfer Function | Pairwise | Directed |
| `eego:PDC` | Partial Directed Coherence | Pairwise | Directed |
| `eego:PowerSpectralDensity` | PSD | SingleChannel | — |
| `eego:SpectralEntropy` | Spectral Entropy | SingleChannel | — |
| `eego:SampleEntropy` | Sample Entropy | SingleChannel | — |
| `eego:ApproximateEntropy` | Approx. Entropy | SingleChannel | — |
| `eego:HjorthActivity` | Hjorth Activity | SingleChannel | — |
