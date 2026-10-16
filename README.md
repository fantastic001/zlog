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
some-command | zlog-analyze SPEC_FILE - [--stdin-labels LABELS] [options]
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
| `--plot-dir DIR` | directory for plot images (default: the `--output` file's directory, or the current directory) |
| `--stdin-labels LABELS` | with `INPUT_DIR` = `-`: the group labels a directory name would give, e.g. `adam-small` |
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

### Reading from stdin

With `-` as `INPUT_DIR`, a single log is read from stdin (at most
`max_input_file_bytes` bytes, decoded with `file_encoding`). It is handled
like one file `0.out` in a single run directory:

* `iteration_separator` splits it into iterations (Definition 2);
* groups read from the log text work as usual (Definition 4);
* the remaining (directory) groups take their labels from `--stdin-labels`,
  split on `group_separator` exactly like a directory name (Definition 1). If
  there are directory groups and too few labels, the run fails with exit
  code `2`.

Checkpointing is not available for stdin, because a stream has no
`(mtime_ns, size)` stamp. `--checkpoint` is ignored with a warning.

```sh
./train.sh | zlog-analyze examples/separated_spec.yaml - --stdin-labels adam
```

*Example.* With `examples/separated_spec.yaml`, $\mathcal{G}_D=(\text{optimizer})$
and $\mathcal{G}_E=\{\text{size}\}$. `--stdin-labels adam` gives
$\kappa=((\text{optimizer},\text{adam}))$, and every iteration's key is
$((\text{optimizer},\text{adam}),(\text{size},V(L)(\text{size})))$.

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
iteration_separator: '^=+ run =+$' # optional, see Definition 2
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

### Collecting lists with `+name`

A name written with a `+` prefix collects values instead of replacing them.
Within one iteration, every line the pattern matches appends its capture,
whatever the match policy is. If the name already holds a single value (from
an earlier pattern), that value becomes the first item of the list. Each
iteration's list is then reported as five metrics: `name.mean`, `name.count`,
`name.stddev`, `name.min`, `name.max` (see Definition 5).

```yaml
groups: [optimizer]
patterns:
  - regex: 'epoch \d+ loss=(\f)'
    names: [+loss]                 # all epochs of the iteration
  - regex: 'accuracy\:\s(\f)'
    names: [accuracy]              # last matching line only
```

Plugins can add more list statistics with
`registry.register_list_statistic("sum", lambda values, ddof: sum(values))`.

### Several iterations in one file

`iteration_separator` is a regex (macros are expanded) that splits each
`*.out` file into several iterations. Every line it matches ends the current
iteration and starts the next one. The separator line itself belongs to
neither. Group labels can then be read from each iteration's text: a group
whose name appears in some pattern's `names` takes its value from that
pattern, and is not reported as a metric. The other groups still come from
the directory name, in declaration order.

```yaml
groups: [optimizer, size]          # optimizer: directory, size: log text
iteration_separator: '^=+ iteration \d+ =+$'
patterns:
  - regex: 'model size\:\s(\w+)'
    names: [size]
  - regex: 'accuracy\:\s(\f)'
    names: [accuracy]
```

```
runs/adam/0.out                    ==== iteration 0 ====
                                   model size: small
                                   accuracy: 0.50
                                   ==== iteration 1 ====
                                   model size: large
                                   accuracy: 0.51
```

This yields the groups `(adam, small)` and `(adam, large)`, one sample each.
See `examples/separated_spec.yaml`.

### Report layout (`report`)

Without a `report` key (or with an empty list), the report is the default
layout: one summary table, then one comparison table per metric. With
`report`, the report is exactly the listed sections, in order. Each entry is
a mapping:

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | section title; unique; also the plot file name |
| `type` | no (`table`) | `table`, `statistics`, `plot`, or a plugin type |
| `description` | no | text printed under the title |
| other keys | | type-specific options, listed below; unknown keys are an error |

**Filters.** A filter selects partitions (group keys) by their labels
(Definition 9):

```yaml
filter: {optimizer: adam}                  # optimizer = adam
filter: {optimizer: adam, size: small}     # optimizer = adam AND size = small
filter: {optimizer: [adam, sgd]}           # optimizer = adam OR optimizer = sgd
filter: [{optimizer: adam}, {size: large}] # (optimizer = adam) OR (size = large)
```

A missing filter selects everything. Every group name in a filter must be
declared in `groups`. Numbers are compared as YAML prints them, so quote
labels like `'01'`.

| Type | Options | Output |
|---|---|---|
| `table` | `filter` | the summary table, restricted to the selected partitions (Definition 10) |
| `statistics` | `first`, `second` (filters), `pooled` (`false` by default) | Mann–Whitney U and Cohen's d for every metric (Definition 11) |
| `plot` | `y` (required), `x`, `filter` | a plot image and the plotted data (Definition 12) |

In `table` and `statistics`, every `+name` list is shown as the metrics
`name.mean`, `name.count`, `name.stddev`, `name.min`, `name.max`
(Definition 5).

`statistics` without `pooled` keeps the rows of the default comparison
tables whose pair joins a partition of `first` and a partition of `second`,
in one table with a `metric` column. With `pooled: true`, all partitions
of `first` form one sample and all partitions of `second` form another, and
each metric gets one row. `--same-distributions-only` applies to both.

`plot` picks the plot kind from `x` and `y`:

| `x` | `y` | Plot |
|---|---|---|
| absent | a scalar metric, e.g. `accuracy` or `loss.mean` | bar plot: one bar per partition, mean ± std, coloured by the first group whose labels differ |
| absent | a `+name` list, e.g. `loss` | line plot: index-wise mean ± std band over the iterations, one line per partition |
| present | any value | scatter plot: one point per pair of values in an iteration, one colour per partition |

`loss.mean` is a single value per iteration, and `loss` is the whole list.
For a scatter plot, `x` and `y` must have the same length in an iteration
(a scalar has length 1); other iterations are skipped with a warning.
Plots are written as `<name>.<plot_format>`, where characters outside
`[A-Za-z0-9._-]` in `name` are replaced by `_`. Markdown embeds them as
images, CSV lists them as `# attachment:` lines and JSON lists them under
`attachments`.

```yaml
groups: [optimizer, size]
patterns:
  - regex: 'epoch \d+ loss=(\f) lr=(\f)'
    names: [+loss, +lr]
  - regex: 'accuracy\:\s(\f)'
    names: [accuracy]
report:
  - name: Adam runs
    filter: {optimizer: adam}
  - name: Adam vs SGD pooled
    type: statistics
    first: {optimizer: adam}
    second: {optimizer: sgd}
    pooled: true
  - name: Loss curve
    type: plot
    filter: {size: small}
    y: loss
```

See `examples/report_spec.yaml`.

## Mathematical definitions

Let $\mathcal{G} = (g_1,\dots,g_k)$ be the declared group names, $D$ the set of
subdirectories of `INPUT_DIR`, and $\sigma$ the separator (`-` by default).

Let $\mathcal{N}$ be the union of all pattern `names`. The groups split into
*extracted* groups $\mathcal{G}_E = \{g \in \mathcal{G} : g \in \mathcal{N}\}$
and *directory* groups $\mathcal{G}_D = (h_1,\dots,h_{k'})$, the
subsequence of $\mathcal{G}$ not in $\mathcal{N}$.

**Definition 1 (directory key).** For $d \in D$ with
$\operatorname{split}_\sigma(d) = (\ell_1,\dots,\ell_m)$, the directory key is
defined iff $m \ge k'$:

$$\kappa(d) = ((h_1,\ell_1),\dots,(h_{k'},\ell_{k'})).$$

Labels after position $k'$ are ignored. If $m < k'$, the directory is skipped
and a warning is logged.

*Example.* $\mathcal{G}=(\text{optimizer},\text{size})$, $\mathcal{N}=\{\text{accuracy}\}$,
$d=\texttt{adam-small-v2}$ gives
$\kappa(d)=((\text{optimizer},\text{adam}),(\text{size},\text{small}))$.

**Definition 2 (iterations).** Let $F=(f_1,\dots,f_n)$ be the lines of one
`*.out` file. Without `iteration_separator`, $F$ is a single iteration. With
separator regex $S$, let $s_1<\dots<s_q$ be the indices of the lines matched
by $S$, and set $s_0=0$, $s_{q+1}=n+1$. The candidate iterations are

$$L_j = (f_{s_j+1},\dots,f_{s_{j+1}-1}), \qquad j=0,\dots,q.$$

Candidates whose lines are all blank are dropped. The remaining ones are
numbered $0,1,\dots$ in order (the `segment` of an `IterationRecord`).

*Example.* $F=(\texttt{a},\ \texttt{===},\ \texttt{===},\ \texttt{b})$ with
$S=\texttt{\^{}===\$}$ gives the candidates $(\texttt{a}), (), (\texttt{b})$, so two
iterations: $(\texttt{a})$ and $(\texttt{b})$.

**Definition 3 (extraction).** Let $L=(l_1,\dots,l_n)$ be the lines of one
iteration and $P$ be a pattern with names $(n_1,\dots,n_r)$. Let
$M_P=\{i : P \text{ matches } l_i\}$. The selected line is
$i^\ast=\max M_P$ for policy `last` or $i^\ast=\min M_P$ for `first`. Nothing
is selected if $M_P=\emptyset$. Name $n_j$ gets the $j$-th captured group of
$l_{i^\ast}$. Call the result $V(L)$, a partial map from names to values,
built by applying the assignments of the patterns in specification order:

* a plain name $n$ assigns $V(n) \leftarrow c$, where $c$ is the capture of
  the selected line, so the later pattern wins;
* a name written `+n` appends, for each $i \in M_P$ in increasing order, the
  capture $c_i$ of line $l_i$:

$$V(n) \leftarrow \begin{cases} (c_i) & n \notin \operatorname{dom} V \\
(v, c_i) & V(n) = v \text{ is a single string} \\
(v_1,\dots,v_p, c_i) & V(n) = (v_1,\dots,v_p). \end{cases}$$

*Example.* With patterns `loss=(\f)` → `[metric]` and `epoch (\d)` →
`[+metric]` on the lines `epoch 1 loss=2`, `epoch 2 loss=1` and policy `last`,
$V(\text{metric}) = (1, 1, 2)$.

**Definition 4 (group key).** For an iteration $L$ of a file in directory $d$,
the group key is defined iff every $g \in \mathcal{G}_E$ is in the domain of
$V(L)$:

$$K(d,L) = ((g_1,\lambda(g_1)),\dots,(g_k,\lambda(g_k))), \qquad
\lambda(g) = \begin{cases} V(L)(g) & g \in \mathcal{G}_E \\
\kappa(d)(g) & g \in \mathcal{G}_D. \end{cases}$$

If it is undefined, the iteration is skipped and a warning is logged. The
metrics of the iteration are $V(L)$ restricted to $\mathcal{N}\setminus\mathcal{G}_E$.

*Example.* $\mathcal{G}_E=\{\text{size}\}$, $\kappa(d)=((\text{optimizer},\text{adam}))$,
$V(L)=\{\text{size}\mapsto\text{small},\ \text{accuracy}\mapsto 0.5\}$ gives
$K=((\text{optimizer},\text{adam}),(\text{size},\text{small}))$ and the metrics
$\{\text{accuracy}\mapsto 0.5\}$.

**Definition 5 (sample).** For a group $G$ and a metric $m$, let
$X_{G,m}=(x_1,\dots,x_N)$ be the values of $m$ over all iterations of $G$,
parsed as IEEE-754 doubles, with `NaN` removed. Non-numeric strings are
dropped and logged. `±inf` is kept.

A list value $V(n) = (v_1,\dots,v_p)$ is not a metric itself. Let
$Y=(y_1,\dots,y_q)$ be its items parsed as doubles, with non-numeric items
and `NaN` removed. It contributes one value per iteration to each of these
metrics ($\delta$ as in Definition 6):

| Metric | Value |
|---|---|
| `n.mean` | $\frac1q\sum_j y_j$, or NaN if $q=0$ |
| `n.count` | $q$ |
| `n.stddev` | $\sqrt{\frac{1}{q-\delta}\sum_j (y_j-\bar y)^2}$, or NaN if $q \le \delta$ |
| `n.min` | $\min_j y_j$, or NaN if $q=0$ |
| `n.max` | $\max_j y_j$, or NaN if $q=0$ |

*Example.* Two iterations with $Y=(1,3)$ and $Y=(5,7,9)$ give
$X_{G,\texttt{n.mean}}=(2,7)$, $X_{G,\texttt{n.count}}=(2,3)$,
$X_{G,\texttt{n.min}}=(1,5)$ and $X_{G,\texttt{n.max}}=(3,9)$.

**Definition 6 (summary).** With $\delta$ = `std_ddof` (default $0$):

$$\bar x = \frac{1}{N}\sum_{i=1}^{N} x_i, \qquad
s = \sqrt{\frac{1}{N-\delta}\sum_{i=1}^{N}(x_i-\bar x)^2}.$$

$\bar x = \text{NaN}$ if $N=0$, and $s=\text{NaN}$ if $N \le \delta$.
The report shows `mean +- std (N=N)`.

*Example.* $X=(1,2,3)$, $\delta=0$: $\bar x = 2$, $s=\sqrt{2/3}\approx 0.816497$,
displayed as `2.000000 +- 0.816497 (N=3)`.

**Definition 7 (Mann–Whitney U).** For samples $X=(x_i)_{i=1}^{n_1}$ and
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

**Definition 8 (Cohen's d).** With population variances $\sigma^2_X$ and
$\sigma^2_Y$:

$$d=\frac{\bar x-\bar y}{\sqrt{(\sigma^2_X+\sigma^2_Y)/2}}.$$

If the denominator is $0$, then $d=\pm\infty$ when $\bar x\neq\bar y$ and
$d=\text{NaN}$ otherwise.

*Example.* $X=(1,2,3)$, $Y=(4,5,6)$: $\bar x-\bar y=-3$ and
$\sigma^2_X=\sigma^2_Y=2/3$, so $d=-3/\sqrt{2/3}\approx-3.674$.

**Pairs.** For every metric, the unordered pairs $\{G,H\}$ with $G<H$
(lexicographic order on keys) that both contain the metric are compared.
This gives $\binom{k'}{2}$ rows for $k'$ such groups.

Let $\mathcal{K}$ be the set of group keys in the summary, and for
$K \in \mathcal{K}$ let $K(g)$ be the label of group $g$ in $K$.

**Definition 9 (filter).** A filter is a non-empty finite family of
alternatives $\Phi = (A_1,\dots,A_r)$. Each alternative maps declared group
names to non-empty label sets, $A_i : \operatorname{dom} A_i \to
2^{\text{labels}}$ with $\operatorname{dom} A_i \subseteq \mathcal{G}$. Then

$$K \models \Phi \iff \exists i \le r\ \forall g \in \operatorname{dom} A_i :
K(g) \in A_i(g).$$

A mapping in the specification is one alternative, a list is several, and a
scalar label $\ell$ stands for $\{\ell\}$. A missing filter is
$\Phi_\top = (\varnothing)$, the single empty alternative, so
$K \models \Phi_\top$ for every $K$. Write
$\mathcal{K}_\Phi = \{K \in \mathcal{K} : K \models \Phi\}$.

*Example.* $\Phi = (\{\text{optimizer}\mapsto\{\text{adam}\},\
\text{size}\mapsto\{\text{small}\}\},\ \{\text{size}\mapsto\{\text{large}\}\})$
selects `(adam, small)`, `(adam, large)` and `(sgd, large)`, but not
`(sgd, small)`.

**Definition 10 (table).** A `table` with filter $\Phi$ is the summary table
of Definition 6 with rows $\mathcal{K}_\Phi$, sorted.

**Definition 11 (statistics).** Let $\Phi_1$ = `first` and $\Phi_2$ = `second`.

* Filtered pairs (default): for every metric $m$, the rows are the pairs
  $\{G,H\}$ of the default comparison (Definitions 7, 8) with
  $(G \models \Phi_1 \wedge H \models \Phi_2) \vee (G \models \Phi_2 \wedge H
  \models \Phi_1)$.
* Pooled (`pooled: true`): for every metric $m$,
  $X_j = X_{G_1,m} \mathbin\Vert \dots \mathbin\Vert X_{G_s,m}$, the
  concatenation over $\mathcal{K}_{\Phi_j}=\{G_1<\dots<G_s\}$. The row compares
  $X_1$ with $X_2$ by Definitions 6–8.

A partition in both $\mathcal{K}_{\Phi_1}$ and $\mathcal{K}_{\Phi_2}$
contributes to both samples.

*Example.* $X_{(\text{adam,small})}=(0,1,2)$, $X_{(\text{adam,large})}=(10,11,12)$,
with $\Phi_1=\{\text{optimizer}\mapsto\{\text{adam}\}\}$, gives
$X_1=(0,1,2,10,11,12)$, $\bar x = 6$ and
$s=\sqrt{154/6}\approx 5.066228$ ($\delta=0$).

**Definition 12 (plot).** Let $\Phi$ be the filter, $R_K$ the iterations
of partition $K \in \mathcal{K}_\Phi$, and for an iteration $L$ let $v_L(n)$
be the numbers of value $n$: the parsed list for a `+n` value, a 1-tuple for
a scalar, and $(\text{stat}(Y))$ for `n.stat` of a list $Y$ (Definition 5).

* Bar ($x$ absent, $y$ never a list in $R_K$): one bar per
  $K$ with $N>0$, of height $\bar x$ and error $s$ of $X_{K,y}$
  (Definition 6). Let $B$ be the plotted keys and
  $c = \min\{j : |\{K(g_j) : K \in B\}| > 1\}$. Bar $K$ gets colour
  $K(g_c)$, and the legend is titled $g_c$. If no such $j$ exists, all bars
  share one colour and there is no legend.

  *Example.* $B = \{(a,b,c), (a,b,e), (a,d,f)\}$: $g_1$ has the single
  label $a$, and $g_2$ has $\{b, d\}$, so $c = 2$. The first two bars
  share colour $b$, and the third gets colour $d$. Group $g_3$ also differs,
  but only the smallest index counts.
* Line ($x$ absent, $y$ a list in some iteration of $\bigcup_K R_K$): for each
  $K$ and index $i$, let $Z_{K,i}=(v_L(y)_i : L \in R_K,\ |v_L(y)|>i)$ with
  NaN removed. The line is $i \mapsto \bar z_{K,i}$ with band
  $\bar z_{K,i} \pm s_{K,i}$, for $0 \le i < \max_L |v_L(y)|$.
* Scatter ($x$ present): the points of $K$ are
  $\{(v_L(x)_i, v_L(y)_i) : L \in R_K,\ |v_L(x)|=|v_L(y)|,\ i < |v_L(y)|\}$,
  without points that have a NaN coordinate.

*Example.* With $v_{L_1}(\text{loss})=(3,1)$ and $v_{L_2}(\text{loss})=(5,3,1)$ in
one partition, $Z_0=(3,5)$, $Z_1=(1,3)$ and $Z_2=(1)$, so the line is
$(4, 2, 1)$ with band half-widths $(1, 1, 0)$.

## Configuration

Settings are layered. A later layer overrides an earlier one:

1. built-in defaults
2. `--config file.toml`, table `[zlog]`
3. environment variables `ZLOG_<SETTING_NAME>`
4. CLI flags (`--format`, `--match-policy`, `--log-level`, `--checkpoint`,
   `--plot-dir`)

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
| `plot_directory` | `""` (next to `--output`, else cwd) | `ZLOG_PLOT_DIRECTORY` |
| `plot_format` | `png` (`png`, `svg`, `pdf`) | `ZLOG_PLOT_FORMAT` |
| `plot_dpi` | `100` (1–1200) | `ZLOG_PLOT_DPI` |

See `examples/zlog.toml`.

## Checkpointing

With `--checkpoint FILE`, the values extracted from each iteration file (one
entry per iteration of Definition 2) are stored under the file's absolute
path, together with its
`(mtime_ns, size)` stamp. The checkpoint is written atomically
(temp file + `os.replace`) every `checkpoint_interval` new records and again
at exit. A later run reuses an entry only when all of these hold:

1. the checkpoint format version matches,
2. the SHA-256 fingerprint of (expanded regexes, names, expanded
   `iteration_separator`, match policy) matches,
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

A report type implements `create_builder(entry, context)`. It validates
`entry.options` and returns an object whose `build(data: ReportData)`
returns a `ReportSection`. The layout sets the section's title and
description from the entry:

```python
from zlog.report_types import require_known_options
from zlog.reporting import ReportSection


class GroupCountBuilder:
    def build(self, data):
        return ReportSection("", ({"groups": len(data.summary)},))


class GroupCountReport:
    def create_builder(self, entry, context):
        require_known_options(entry, ())
        return GroupCountBuilder()


def register(registry: PluginRegistry) -> None:
    registry.register_report_type("count", GroupCountReport())
```

Lifecycle hooks: a hook implements any subset of these methods.

| Event | Method | Called |
|---|---|---|
| load | `on_load(spec: AnalysisSpec)` | once, before scanning |
| execute | `on_iteration_analyzed(record: IterationRecord)` | after every iteration (values are `str` or, for `+name`, `tuple[str, ...]`) |
| terminate | `on_terminate(summary: Summary)` | once, after aggregation |

When a hook raises an exception, it is logged at `ERROR` level and the
analysis continues. Set `ZLOG_PLUGINS=off` to turn off plugin loading.

## Architecture

```
cli ──► application (composition root)
           ├─ spec_loader   SpecParser / SpecLoader (YAML, JSON; table of decoders)
           ├─ regex_macros  RegexMacroExpander
           ├─ inputs        InputChannel: DirectoryInput / StdinInput
           ├─ discovery     RunSource: DirectoryRunSource / StdinRunSource
           │                RunDirectoryScanner, GroupLabelParser → GroupRun
           ├─ extraction    IterationSplitter (WholeFile / SeparatorLine),
           │                TextReader (BoundedFile / BoundedStream),
           │                SegmentedTextExtractor, SourceValueExtractor
           ├─ grouping      partition_group_names, SegmentGroupResolver
           ├─ checkpoint    CheckpointedExtractor (decorator), Json/Null CheckpointStore
           ├─ pipeline      AnalysisPipeline (+ hooks.HookDispatcher)
           ├─ capture_names parse_capture_name (`+name` → AssignmentMode.APPEND)
           ├─ aggregation   MetricAggregator         → Summary
           ├─ list_statistics ListStatisticsReducer (table of list statistics)
           ├─ statistics    DistributionTest protocol, MannWhitneyUTest, compute_cohen_d
           ├─ comparison    MetricComparator, PairwiseComparisonBuilder
           ├─ reporting     ReportSection builders, cell formatters,
           │                DefaultReportLayout
           ├─ group_filter  GroupFilter, GroupFilterParser (Definition 9)
           ├─ report_types  ReportType table: table / statistics / plot,
           │                ReportLayoutFactory → ConfiguredReportLayout
           ├─ plotting      PlotDataBuilder per PlotKind (bar/line/scatter)
           ├─ plot_drawing  PlotFileLocator, MatplotlibPlotWriter, drawers
           └─ renderers     Markdown / CSV / JSON renderers (OutputFormatPlugin table)
```

## Differences from `analyze.py`

* The summary is always a single table sorted by group key. With one group
  column, the old script printed one table per group and showed the raw tuple
  as the group value.
* The comparison tables cover every metric seen in any group, not only the
  metrics of the first group. They also always include a `same_distribution`
  column.
* `--verbose` output goes to stderr, so stdout carries only the report. Each
  line also shows the `Segment` (iteration index inside the file).
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
