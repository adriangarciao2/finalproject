# JaCoCo Coverage Summary (d2l)

Short coverage snapshot generated from the JaCoCo HTML report in `d2l/target/site/jacoco/index.html`.

- **Instruction coverage:** ~94.9% (missed 2,816 of 55,177)
- **Branch coverage:** ~91.2% (missed 719 of 8,178)
- **Line coverage:** ~94.4% (as reported in the HTML summary)

Report location: `d2l/target/site/jacoco/index.html` (open in a browser to view detailed per-class metrics).

Notes:
- JaCoCo instrumentation is configured in `d2l/pom.xml` and excludes `org/apache/commons/lang3/reflect/testbed/**` to avoid probe-field interference with reflection-based tests.
- To regenerate this report locally: run `mvn -f d2l clean verify` from the repo root.
