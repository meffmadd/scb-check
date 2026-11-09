# Category coupling

Terminology for class dependencies across categories. The analyzer's selected measurement policy is defined in [Architecture](docs/architecture.md#category-coupling-ca-and-ce).

## Language

**Category**:
A grouping of classes whose incoming and outgoing dependencies are measured together.
_Avoid_: Arbitrary directory, module neighbor

**Client class**:
The source class of a directed dependency on another class.

**Afferent coupling (Ca)**:
The number of distinct classes outside a category that depend on classes inside it.
_Avoid_: Incoming module count, importing-file count

**Efferent coupling (Ce)**:
The number of distinct classes inside a category that depend on any class outside it.
_Avoid_: External target breadth, outgoing module count

**Partial measurement**:
A count of supported evidence that may omit unknown relationships; an observed zero does not establish absence.

**Unavailable measurement**:
A measurement lacking required extraction support, excluded from measured-population summaries rather than counted as zero.
