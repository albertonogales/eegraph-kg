# EEGraph KG Exporter

Convert EEG connectivity data computed with [EEGraph](https://github.com/ufvceiec/EEGRAPH) into a FAIR Knowledge Graph (RDF/Turtle) using established Semantic Web ontologies.

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21327761.svg)](https://doi.org/10.5281/zenodo.21327761)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Overview

This tool sits **outside** the EEGraph library but is designed to work with its output. It takes windowed connectivity graphs produced by EEGraph and serialises them as RDF knowledge graphs conforming to the **eego:** application ontology, grounded in:

- [SOSA/SSN](https://www.w3.org/TR/vocab-ssn/) — sensors and observations  
- [OWL-Time](https://www.w3.org/TR/owl-time/) — temporal intervals  
- [PROV-O](https://www.w3.org/TR/prov-o/) — provenance  
- [SKOS](https://www.w3.org/TR/skos-reference/) — concept schemes for connectivity measure metadata  
- [SIO](https://sio.semanticscience.org/) — scientific information  
- [Schema.org](https://schema.org/)

The resulting KG is queryable via SPARQL and published on [TriplyDB](https://triplydb.com/AlbertoNogalesMoyano/Knowledge-Graph-EEG).

## Repository structure

```
eegraph-kg-exporter/
├── eegraph_ext/
│   ├── kg.py          # EEGKGExporter + EEGraphKGExporter classes
│   ├── eego.ttl       # eego: application ontology (OWL + SKOS)
│   └── __init__.py
├── kg_pipeline.py     # End-to-end pipeline: EDF → EEGraph → KG
├── kg/                # Pre-built knowledge graphs
│   ├── chb01_ctrl.ttl     # CHB-MIT Subject 01, interictal (control)
│   ├── chb01_ictal.ttl    # CHB-MIT Subject 01, ictal (seizure)
│   ├── S001_rest.ttl      # EEGMMIDB Subject 01, eyes-open rest
│   └── S001_task.ttl      # EEGMMIDB Subject 01, motor imagery task
├── docs/
│   ├── usage.md           # Step-by-step guide
│   └── sparql_examples.md # Example SPARQL queries
└── requirements.txt
```

## Quick start

### 1. Install dependencies

```bash
pip install eegraph rdflib mne networkx numpy
```

> Tested with EEGraph 0.1.0, rdflib 7.x, MNE 1.x.

### 2. Run on your own EDF file

```python
from kg_pipeline import build_kg_from_edf

kg, windows, channels = build_kg_from_edf(
    edf_path="path/to/your/file.edf",
    window_size=60,          # seconds per window
    threshold=0.7,           # connectivity threshold (Pearson |r|)
    output_turtle="my_kg.ttl"
)
print(f"Generated {len(kg)} triples across {len(windows)} windows")
```

### 3. Run on MNE-cached data (EEGMMIDB)

```python
from kg_pipeline import build_kg_from_raws

kg = build_kg_from_raws(
    subject=1,
    runs=[4, 8, 12],         # motor imagery runs
    window_size=60,
    output_turtle="S001_task.ttl"
)
```

### 4. Inspect the KG

Load any of the pre-built KGs in `kg/`:

```python
from rdflib import Dataset

ds = Dataset()
ds.parse("kg/chb01_ctrl.ttl", format="trig")
print(f"{len(list(ds.quads()))} triples in {len(list(ds.graphs()))} named graphs")
```

Or query the live SPARQL endpoint:  
**https://triplydb.com/AlbertoNogalesMoyano/Knowledge-Graph-EEG/sparql**

## Ontology

The `eego:` ontology (`eegraph_ext/eego.ttl`) defines:

| Class | Description |
|---|---|
| `eego:ConnectivityMeasure` | Named individual for each measure (Pearson, PLV, …) |
| `eego:NodeMeasurement` | Observation of a connectivity value at a sensor pair |
| `eego:MeasureScope` | SKOS concept: `Pairwise` or `SingleChannel` |
| `eego:MeasureSymmetry` | SKOS concept: `Symmetric`, `Asymmetric`, `Antisymmetric`, `Directed` |
| `eego:ThresholdRule` | SKOS concept: `ValueAbove`, `MagnitudeAboveUndirected`, `TopFraction` |

Ontology IRI: `http://eegraph.org/ontology#`

## Datasets

| Dataset | Source | Recording | KG file | Triples |
|---|---|---|---|---|
| CHB-MIT chb01 interictal | [PhysioNet](https://physionet.org/content/chbmit/) | chb01_01.edf | `chb01_ctrl.ttl` | 7,485 |
| CHB-MIT chb01 ictal | [PhysioNet](https://physionet.org/content/chbmit/) | chb01_03.edf | `chb01_ictal.ttl` | 6,911 |
| EEGMMIDB S001 rest | [PhysioNet](https://physionet.org/content/eegmmidb/) | R01+R02 | `S001_rest.ttl` | 58,564 |
| EEGMMIDB S001 task | [PhysioNet](https://physionet.org/content/eegmmidb/) | R04+R08+R12 | `S001_task.ttl` | 174,955 |

Full archive: [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21327761.svg)](https://doi.org/10.5281/zenodo.21327761)

## Citation

If you use this tool or the knowledge graphs in your research, please cite:

> Nogales, A., et al. (2025). *From Brain Signal Connectivity to a FAIR Knowledge Graph*. [Journal TBD].  
> Data: https://doi.org/10.5281/zenodo.21327761

## License

Code: [MIT](LICENSE)  
Ontology and KG data: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
