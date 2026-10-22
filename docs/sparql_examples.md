# SPARQL Query Examples

Live endpoint: **https://triplydb.com/AlbertoNogalesMoyano/Knowledge-Graph-EEG/sparql**

---

## 1. Count triples per named graph (window)

```sparql
SELECT ?g (COUNT(*) AS ?triples) WHERE {
  GRAPH ?g { ?s ?p ?o }
}
GROUP BY ?g
ORDER BY ?g
```

---

## 2. List all connectivity observations in one window

```sparql
PREFIX eego: <http://eegraph.org/ontology#>
PREFIX sosa: <http://www.w3.org/ns/sosa/>

SELECT ?source ?target ?value WHERE {
  GRAPH eego:window/chb01_01.edf_0 {
    ?obs a eego:NodeMeasurement ;
         eego:sourceNode ?source ;
         eego:targetNode ?target ;
         sosa:hasSimpleResult ?value .
  }
}
ORDER BY DESC(?value)
```

---

## 3. Provenance — parameters used

```sparql
PREFIX eego: <http://eegraph.org/ontology#>
PREFIX prov: <http://www.w3.org/ns/prov#>

SELECT ?param ?value WHERE {
  GRAPH eego:provenance {
    ?act a prov:Activity .
    ?act ?param ?value .
  }
}
```

---

## 4. All electrodes (sensors) and their positions

```sparql
PREFIX eego: <http://eegraph.org/ontology#>
PREFIX sosa: <http://www.w3.org/ns/sosa/>
PREFIX schema: <https://schema.org/>

SELECT ?electrode ?label WHERE {
  GRAPH eego:electrodes {
    ?electrode a sosa:Sensor ;
               schema:name ?label .
  }
}
ORDER BY ?label
```

---

## 5. Top-10 most connected channel pairs (across all windows)

```sparql
PREFIX eego: <http://eegraph.org/ontology#>
PREFIX sosa: <http://www.w3.org/ns/sosa/>

SELECT ?source ?target (AVG(?value) AS ?avgR) (COUNT(*) AS ?windows) WHERE {
  ?obs a eego:NodeMeasurement ;
       eego:sourceNode ?source ;
       eego:targetNode ?target ;
       sosa:hasSimpleResult ?value .
}
GROUP BY ?source ?target
ORDER BY DESC(?avgR)
LIMIT 10
```

---

## 6. Connectivity measure metadata

```sparql
PREFIX eego: <http://eegraph.org/ontology#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?measure ?label ?scope ?symmetry WHERE {
  ?measure a eego:ConnectivityMeasure ;
           rdfs:label ?label ;
           eego:scope ?scopeNode ;
           eego:symmetry ?symNode .
  ?scopeNode skos:prefLabel ?scope .
  ?symNode   skos:prefLabel ?symmetry .
}
```

---

## 7. Windows in temporal order

```sparql
PREFIX eego:  <http://eegraph.org/ontology#>
PREFIX time:  <http://www.w3.org/2006/time#>

SELECT ?window ?start ?end WHERE {
  ?window a eego:TimeWindow ;
          time:hasBeginning/time:inXSDDateTimeStamp ?start ;
          time:hasEnd/time:inXSDDateTimeStamp ?end .
}
ORDER BY ?start
```
