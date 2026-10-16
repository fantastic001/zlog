# zlog

`zlog` pulls numeric metrics out of the text logs of repeated experiment runs.
It summarizes each metric per experiment group and tests every pair of groups
statistically, to check whether they come from the same distribution.

It replaces the earlier single-file `analyze.py` script. The command-line
interface stays compatible.

## Installation

Requires Python ≥ 3.11.

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"      # library + CLI + test tooling
# or, runtime only, pinned:
.venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e .
```

## Usage

```sh
zlog-analyze SPEC_FILE INPUT_DIR [options]
python -m zlog SPEC_FILE INPUT_DIR [options]
```

| Option | Meaning |
|---|---|
| `--verbose` | print the values extracted from every iteration (to stderr) |
| `--same-distributions-only` | keep only the pairs where the null hypothesis is **not** rejected |
| `--format {markdown,csv,json,…}` | report format; plugins can add more |
| `--match-policy {first,last}` | which matching line wins when a pattern matches several lines (default `last`, same as the original script) |
| `--config FILE` | TOML configuration file (see [Configuration](#configuration)) |
| `--checkpoint FILE` | cache extracted values in a JSON checkpoint; re-runs skip unchanged files |
| `--restart` | ignore an existing checkpoint and recompute everything |
| `--output FILE` | write the report to a file instead of stdout |
| `--log-level LEVEL` | `DEBUG`, `INFO`, `WARNING` (default), `ERROR` |

Exit codes: `0` for success, `2` for a usage, configuration or specification
error, and `1` for an I/O failure.

### Input layout

```
INPUT_DIR/
├── adam-small/          # directory name = group labels joined by "-"
│   ├── 0.out            # iteration 0
│   ├── 1.out
│   └── 2.out
└── sgd-small/
    ├── 0.out
    └── 1.out
```

### Specification file (YAML or JSON)

```yaml
groups: [optimizer, size]          # names of the "-"-separated labels
patterns:
  - regex: 'accuracy\:\s(\f)'      # macros are expanded, see below
    names: [accuracy]
  - regex: 'loss=(\f) time=(\f)'
    names: [loss, time]
macros:                            # optional, user-defined macros
  '\i': '\d+'
```

Built-in regex macros are expanded in this order: built-ins first, then
plugin macros, then `macros` from the specification.

| Macro | Expansion | Matches |
|---|---|---|
| `\f` | `[+-]?(?:\d*\.?\d+\|\b(?:nan\|inf(?:inity)?)\b)` | a decimal number, `nan`, `inf`, `infinity` |
| `\:` | `[^:]*:` | everything up to and including the next colon |
| `\s` | `\s*` | optional whitespace (so do **not** write `\s*` yourself) |

Every capturing group of a pattern is assigned to the name at the same
position in `names`.

## Mathematical definitions

Let $\mathcal{G} = (g_1,\dots,g_k)$ be the declared group names, $D$ the set of
subdirectories of `INPUT_DIR`, and $\sigma$ the separator (`-` by default).

**Definition 1 (group key).** For $d \in D$ with $\operatorname{split}_\sigma(d)
= (\ell_1,\dots,\ell_m)$, the key is defined iff $m \ge k$:

$$\kappa(d) = ((g_1,\ell_1),\dots,(g_k,\ell_k)).$$

Labels after position $k$ are ignored. If $m < k$, the directory is skipped and
a warning is logged.

*Example.* $\mathcal{G}=(\text{optimizer},\text{size})$, $d=\texttt{adam-small-v2}$
gives $\kappa(d)=((\text{optimizer},\text{adam}),(\text{size},\text{small}))$.

**Definition 2 (extraction).** Let $L=(l_1,\dots,l_n)$ be the lines of one
iteration file and $P$ be a pattern with names $(n_1,\dots,n_r)$. Let
$M_P=\{i : P \text{ matches } l_i\}$. The selected line is
$i^\ast=\max M_P$ for policy `last` or $i^\ast=\min M_P$ for `first`. Nothing
is selected if $M_P=\emptyset$. Name $n_j$ gets the $j$-th captured group of
$l_{i^\ast}$. When patterns share a name, the later pattern in the
specification wins.

**Definition 3 (sample).** For a group $G$ and a metric $m$, let
$X_{G,m}=(x_1,\dots,x_N)$ be the values of $m$ over all iterations of $G$,
parsed as IEEE-754 doubles, with `NaN` removed. Non-numeric strings are
dropped and logged. `±inf` is kept.

**Definition 4 (summary).** With $\delta$ = `std_ddof` (default $0$):

$$\bar x = \frac{1}{N}\sum_{i=1}^{N} x_i, \qquad
s = \sqrt{\frac{1}{N-\delta}\sum_{i=1}^{N}(x_i-\bar x)^2}.$$

$\bar x = \text{NaN}$ if $N=0$, and $s=\text{NaN}$ if $N \le \delta$.
The report shows `mean +- std (N=N)`.

*Example.* $X=(1,2,3)$, $\delta=0$: $\bar x = 2$, $s=\sqrt{2/3}\approx 0.816497$,
displayed as `2.000000 +- 0.816497 (N=3)`.

**Definition 5 (Mann–Whitney U).** For samples $X=(x_i)_{i=1}^{n_1}$ and
$Y=(y_j)_{j=1}^{n_2}$:

$$U_X=\sum_{i=1}^{n_1}\sum_{j=1}^{n_2}\Big(\mathbf 1[x_i>y_j]+\tfrac12\,\mathbf 1[x_i=y_j]\Big),$$

with the two-sided p-value computed by `scipy.stats.mannwhitneyu`. Given the
significance level $\alpha$ (default $0.05$), the column
`same_distribution` is $p > \alpha$, which means $H_0: F_X = F_Y$ is not
rejected. The test runs only if $n_1,n_2 \ge$ `minimum_sample_size`
(default $2$). Otherwise every column of the pair is empty.

*Example.* $X=(1,2,3)$, $Y=(4,5,6)$: every $x_i<y_j$, so $U_X=0$ and
$p=0.1$. With $\alpha=0.05$, `same_distribution = True`. Three samples per
group are too few to reject $H_0$.

**Definition 6 (Cohen's d).** With population variances $\sigma^2_X$ and
$\sigma^2_Y$:

$$d=\frac{\bar x-\bar y}{\sqrt{(\sigma^2_X+\sigma^2_Y)/2}}.$$

If the denominator is $0$, then $d=\pm\infty$ when $\bar x\neq\bar y$ and
$d=\text{NaN}$ otherwise.

*Example.* $X=(1,2,3)$, $Y=(4,5,6)$: $\bar x-\bar y=-3$ and
$\sigma^2_X=\sigma^2_Y=2/3$, so $d=-3/\sqrt{2/3}\approx-3.674$.

**Pairs.** For every metric, the unordered pairs $\{G,H\}$ with $G<H$
(lexicographic order on keys) that both contain the metric are compared.
This gives $\binom{k'}{2}$ rows for $k'$ such groups.

## Configuration

Settings are layered. A later layer overrides an earlier one:

1. built-in defaults
2. `--config file.toml`, table `[zlog]`
3. environment variables `ZLOG_<SETTING_NAME>`
4. CLI flags (`--format`, `--match-policy`, `--log-level`, `--checkpoint`)

| Setting | Default | Env var |
|---|---|---|
| `significance_level` | `0.05` | `ZLOG_SIGNIFICANCE_LEVEL` |
| `minimum_sample_size` | `2` | `ZLOG_MINIMUM_SAMPLE_SIZE` |
| `std_ddof` | `0` | `ZLOG_STD_DDOF` |
| `group_separator` | `-` | `ZLOG_GROUP_SEPARATOR` |
| `output_extension` | `.out` | `ZLOG_OUTPUT_EXTENSION` |
| `file_encoding` | `utf-8` | `ZLOG_FILE_ENCODING` |
| `max_input_file_bytes` | `268435456` | `ZLOG_MAX_INPUT_FILE_BYTES` |
| `match_policy` | `last` | `ZLOG_MATCH_POLICY` |
| `output_format` | `markdown` | `ZLOG_OUTPUT_FORMAT` |
| `log_level` | `WARNING` | `ZLOG_LOG_LEVEL` |
| `plugins` (feature flag) | `enabled` | `ZLOG_PLUGINS` (`on/off/true/false/1/0`) |
| `checkpoint_file` | `""` (disabled) | `ZLOG_CHECKPOINT_FILE` |
| `checkpoint_interval` | `100` | `ZLOG_CHECKPOINT_INTERVAL` |

See `examples/zlog.toml`.

## Checkpointing

With `--checkpoint FILE`, the values extracted from each iteration file are
stored under the file's absolute path, together with its
`(mtime_ns, size)` stamp. The checkpoint is written atomically
(temp file + `os.replace`) every `checkpoint_interval` new records and again
at exit. A later run reuses an entry only when all of these hold:

1. the checkpoint format version matches,
2. the SHA-256 fingerprint of (expanded regexes, names, match policy) matches,
3. the file's stamp is unchanged.

So an interrupted run continues where it stopped, and changing the
specification invalidates the cache automatically. `--restart` ignores the
checkpoint.

## Plugins

A plugin is an installed distribution that declares an entry point in the
`zlog.plugins` group. The entry point is a callable that receives the
`PluginRegistry`:

```toml
# plugin's pyproject.toml
[project.entry-points."zlog.plugins"]
my_plugin = "my_plugin:register"
```

```python
from zlog.plugins import PluginRegistry
from zlog.renderers import OutputFormatPlugin
from zlog.reporting import TextMetricCellFormatter


class HtmlRenderer:
    def render(self, sections):
        ...


class SlackNotifier:
    def on_terminate(self, summary):
        ...


def register(registry: PluginRegistry) -> None:
    registry.register_output_format(
        "html", OutputFormatPlugin(HtmlRenderer, TextMetricCellFormatter)
    )
    registry.register_hook(SlackNotifier())
    registry.register_regex_macro(r"\i", r"\d+")
```

Lifecycle hooks: a hook implements any subset of these methods.

| Event | Method | Called |
|---|---|---|
| load | `on_load(spec: AnalysisSpec)` | once, before scanning |
| execute | `on_iteration_analyzed(record: IterationRecord)` | after every iteration file |
| terminate | `on_terminate(summary: Summary)` | once, after aggregation |

When a hook raises an exception, it is logged at `ERROR` level and the
analysis continues. Set `ZLOG_PLUGINS=off` to turn off plugin loading.

## Architecture

```
cli ──► application (composition root)
           ├─ spec_loader   SpecParser / SpecLoader (YAML, JSON; table of decoders)
           ├─ regex_macros  RegexMacroExpander
           ├─ discovery     RunDirectoryScanner      → GroupRun[IterationSource]
           ├─ extraction    TextValueExtractor, FileValueExtractor (ValueExtractor protocol)
           ├─ checkpoint    CheckpointedExtractor (decorator), Json/Null CheckpointStore
           ├─ pipeline      AnalysisPipeline (+ hooks.HookDispatcher)
           ├─ aggregation   MetricAggregator         → Summary
           ├─ statistics    DistributionTest protocol, MannWhitneyUTest, compute_cohen_d
           ├─ comparison    MetricComparator, PairwiseComparisonBuilder
           ├─ reporting     ReportSection builders, cell formatters
           └─ renderers     Markdown / CSV / JSON renderers (OutputFormatPlugin table)
```

## Differences from `analyze.py`

* The summary is always a single table sorted by group key. With one group
  column, the old script printed one table per group and showed the raw tuple
  as the group value.
* The comparison tables cover every metric seen in any group, not only the
  metrics of the first group. They also always include a `same_distribution`
  column.
* `--verbose` output goes to stderr, so stdout carries only the report.
* The old script expanded macros in place on every file, so a pattern using
  `\s` became `\s**` on the second iteration and crashed with
  `multiple repeat`. Macros are now expanded once, when the pattern is compiled.
* The old script crashed on non-numeric `*.out` names, non-numeric
  captures, unmatched optional groups and an empty input directory. These
  cases are now skipped with a log message.
* Markdown cells are HTML-escaped and `|` is escaped. CSV cells that start
  with `=`, `@`, TAB or CR get a `'` prefix to block spreadsheet formula
  injection. Spec and input files are size-limited.

## Development

```sh
.venv/bin/pytest            # tests + branch coverage (fails under 80 %)
.venv/bin/ruff check src tests
.venv/bin/ruff format src tests
.venv/bin/mypy src          # strict
```
