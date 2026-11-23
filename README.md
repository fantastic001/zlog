# zlog

`zlog` turns log files into tables. It reads each log line by line, matches
every line against an ordered list of regex **rules**, and writes one CSV (or
JSON) row per matched line. Captured groups and constants are stored in
variables of two kinds:

* **context** variables keep their value from line to line until a rule
  changes or resets them, so they describe the *state* of the log;
* **record** variables belong to the matched line only.

Every row has the columns `path`, then all context variables, then all record
variables. A variable without a value is an empty cell.

## Installation

Requires Python ≥ 3.11.

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"      # library + CLI + test tooling
# or, runtime only, pinned:
.venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e .
```

## Quick start

`examples/train.log`:

```
==== run adam ====
epoch 1 loss=0.90 acc=0.50
processed 100 samples
epoch 2 loss=0.70 acc=0.61
warning: lr-high
processed 150 samples
warning: nan-loss
==== run sgd ====
epoch 1 loss=1.20 acc=0.40
debug: unmatched line
```

`examples/train.yaml`:

```yaml
matches:
  - pattern: '^=+ run %(=run)w'   # a word, stored in context variable run
    reset: [epoch, samples, warnings]
    context:
      +run_index: {value: 1}      # + adds; a constant 1 counts runs
    record:
      event: {value: start}       # a constant tags the row
  - pattern: 'epoch %(=epoch)d loss=%(loss)f acc=%(acc)f'
    record: {event: {value: epoch}}
  - pattern: 'processed %(+samples)d samples'   # + adds to samples
    record: {event: {value: progress}}
  - pattern: 'warning: %(@warnings)s'           # @ concatenates
    record: {event: {value: warning}}
```

`%w`, `%d`, `%f` and `%s` are [pattern aliases](#pattern-aliases) for a
word, an integer, a number and text up to whitespace. The name in
parentheses [binds the capture](#capture-bindings): `%(loss)f` stores it in
the record variable `loss`, while `%(=epoch)d`, `%(+samples)d` and
`%(@warnings)s` replace, add to or concatenate onto a context variable.

```sh
zlog -s examples/train.yaml examples/train.log --concat-separator '|'
```

```
path,run,run_index,epoch,samples,warnings,event,loss,acc
examples/train.log,adam,1,,,,start,,
examples/train.log,adam,1,1,,,epoch,0.90,0.50
examples/train.log,adam,1,1,100,,progress,,
examples/train.log,adam,1,2,100,,epoch,0.70,0.61
examples/train.log,adam,1,2,100,lr-high,warning,,
examples/train.log,adam,1,2,250,lr-high,progress,,
examples/train.log,adam,1,2,250,lr-high|nan-loss,warning,,
examples/train.log,sgd,2,,,,start,,
examples/train.log,sgd,2,1,,,epoch,1.20,0.40
```

The same rules can be given on the command line, without a spec file:

```sh
zlog --concat-separator '|' \
  -p '^=+ run %(=run)w' --reset epoch --reset samples --reset warnings \
     -c +run_index:=1 -r event:=start \
  -p 'epoch %(=epoch)d loss=%(loss)f acc=%(acc)f' -r event:=epoch \
  -p 'processed %(+samples)d samples' -r event:=progress \
  -p 'warning: %(@warnings)s' -r event:=warning \
  examples/train.log
```

## Usage

```
zlog [-s SPEC] [-p REGEX [BINDING OPTIONS]...]... [INPUT ...] [options]
python -m zlog ...
```

`INPUT` is a log file, or `-` for stdin. Without inputs, `zlog` reads stdin.
Rule options and inputs may be interleaved.

| Option | Meaning |
|---|---|
| `-s`, `--spec FILE` | YAML (`.yaml`, `.yml`, other) or JSON (`.json`) specification |
| `-p`, `--pattern REGEX` | start a rule; REGEX may use [aliases](#pattern-aliases) and [capture bindings](#capture-bindings); write `--pattern=-…` for a regex that starts with `-` |
| `-c`, `--context BINDING` | add a context binding to the current rule |
| `-r`, `--record BINDING` | add a record binding to the current rule |
| `--reset NAME` | clear context variable `NAME` before the current rule's updates (repeatable) |
| `--reset-all` | clear every context variable before the current rule's updates |
| `-o`, `--output FILE` | write to `FILE` instead of stdout |
| `--format {csv,json,jsonl,…}` | output format; plugins can add more |
| `--concat-separator TEXT` | text placed between values joined with `@` |
| `--csv-delimiter CHAR` | CSV field delimiter, e.g. `';'` or `$'\t'` |
| `--formula-escaping {off,quote,tab}` | see [Spreadsheet formulas](#spreadsheet-formulas) |
| `--encoding NAME` | encoding of the inputs |
| `--config FILE` | TOML configuration file (see [Configuration](#configuration)) |
| `--log-level LEVEL` | `DEBUG`, `INFO`, `WARNING` (default), `ERROR` |

Rules from `--spec` come first; command-line rules are appended after them.

## Specification

### File format

```yaml
aliases:                 # optional: pattern aliases, see below
  ts: '\d{2}:\d{2}:\d{2}'
matches:                 # required: a non-empty list of rules, in order
  - pattern: PATTERN     # required: a regex with aliases and captures
    reset: all | [NAME, ...]          # optional
    context: {NAME: SOURCE, ...}      # optional
    record:  {NAME: SOURCE, ...}      # optional
```

Unknown keys are an error, and so are duplicate keys (which plain YAML
loaders silently drop).

### Variable names and prefixes

A name matches `[A-Za-z_][A-Za-z0-9_.]*`. A **context** name may carry a
prefix that selects how a new value $c$ is combined with the current value
$x$:

| Prefix | Update | Result |
|---|---|---|
| none | replace | $c$ |
| `+` | add numerically | $x + c$, where an unset $x$ counts as $0$ |
| `@` | concatenate | $c$ if $x$ is unset, else $x \mathbin\Vert s \mathbin\Vert c$ with $s$ = `concat_separator` |

Record names take no prefix. YAML cannot start an unquoted key with `@`, so
write `"@warnings": 1` (or capture with `%(@warnings)s`). One context
variable may use different prefixes in different rules: `C` in one rule and
`+C` in another is allowed.

### Value sources

| Source | YAML | Command line | Value |
|---|---|---|---|
| group by index | `loss: 2` | `-r loss=2` or `-r loss` (next unnamed group) | capture of group 2; `0` is the whole match |
| group by name | `size: size` | `-c size=size` | capture of `%(size)d` or `(?P<size>…)` |
| constant | `event: {value: start}` | `-r event:=start` | the text `start` |

A capture such as `%(loss)f` needs no entry at all; see
[Capture bindings](#capture-bindings). A group reference that does not exist
in the pattern is an error before any input is read.

*Why constants are not plain strings.* YAML types unquoted values, so
`phase: 1` is the integer `1` (group 1) while `phase: "1"` is a string, and
`yes` is a boolean. The `{value: …}` form makes the meaning independent of
quoting. Constants may be strings, integers or floats. Booleans and `null`
are errors. Write constants in quotes when the exact text matters: `010` is
the integer $8$ in YAML and `0.10` is the float $0.1$.

### Command-line bindings

A binding is `NAME`, `NAME=GROUP` or `NAME:=VALUE`. Within a rule, the
$k$-th binding written as a bare `NAME` takes the $k$-th **unnamed** group,
counting `-c` and `-r` together in the order written. Named groups, both
`%(…)` captures and `(?P<n>…)`, are skipped, because they are referenced by
name. Explicit references and constants do not advance the count.

*Example.* `-p 'epoch %d loss=%f' -c epoch -r tag:=e -r loss` binds
`epoch` to group 1, `tag` to the constant `e`, and `loss` to group 2. In
`-p 'run %(=run)w epoch %d' -c epoch`, the capture binds `run` and `epoch`
takes group 2, the first unnamed group. In `--pattern P1 --record A --record
B --context C --pattern P2 --record A --context +C`, where `P1` and `P2` have
no named groups, rule `P1` binds `A`, `B`, `C` to groups 1, 2, 3, and rule
`P2` binds `A` and `+C` to groups 1 and 2.

The YAML file and the command line build the same rules; the test
`test_cli_form_of_the_example_equals_the_yaml_spec` checks this for the
example above.

### Pattern aliases

A pattern is a Python regex in which `%` starts an **alias**. An alias stands
for a regex and, unless suppressed, brings its own capturing group, so
`loss=%f` means `loss=(…number…)`. The built-in aliases are:

| Alias | Regex | Matches | Examples |
|---|---|---|---|
| `%d` | `[+-]?\d+` | an integer | `42`, `-12` |
| `%f` | `[+-]?(?:(?:\d+(?:\.\d*)?\|\.\d+)(?:[eE][+-]?\d+)?\|(?i:\bnan\b\|\binf(?:inity)?\b))` | a decimal number with optional exponent, or `nan`, `inf`, `infinity` in any case | `0.90`, `1.5e-3`, `-.5`, `NaN` |
| `%x` | `(?:0[xX])?[0-9A-Fa-f]+` | a hexadecimal number | `0x1F`, `ff` |
| `%s` | `\S+` | text up to the next whitespace, as in C `scanf` | `lr-high` |
| `%w` | `\w+` | a word: letters, digits and `_` | `adam` |
| `%r` | `.*` | the rest of the line | `any text` |

Write $\mathcal{A}(a)$ for the regex of alias $a$:

| Written | Expands to | Groups |
|---|---|---|
| `%a` or `%{a}` | `(`$\mathcal{A}(a)$`)` | one, the next group number |
| `%(`$\sigma n$`)a` or `%(`$\sigma n$`){a}` | `(?P<n>`$\mathcal{A}(a)$`)` | one, also named `n`, and bound to the variable `n` ([capture bindings](#capture-bindings)) |
| `%*a` or `%*{a}` | `(?:`$\mathcal{A}(a)$`)` | none |
| `%%` | `%` | none |

The short form `%a` takes a single letter; `%{a}` takes any alias name. In
`%(`$\sigma n$`)`, $\sigma$ is an optional prefix such as `=`, `+` or `@`
and $n$ a name.

**Custom aliases.** `aliases: {ts: '\d{2}:\d{2}:\d{2}'}` in the
specification defines `%{ts}` (or `%(time){ts}` to bind the record variable
`time`).
Plugins add aliases with `register_pattern_alias`. Built-ins come first, then
plugin aliases, then `aliases` from the specification; a later definition of
the same name wins, so `aliases: {d: '\d+'}` replaces `%d`. An alias name
matches `[A-Za-z_][A-Za-z0-9_]*`, and its regex must compile and must not
contain capturing groups (write `(?:…)` inside an alias).

**Definition A (alias expansion).** Let $\mathcal{A}$ be the alias table, a
finite map from alias names to regexes without capturing groups. The expansion
$E(P)$ of a pattern $P$ scans $P$ once from left to right and replaces each
token:

1. a backslash and the character after it, `\c`, are copied unchanged, so
   `\%d` matches the text `%d`;
2. `%%` becomes `%`;
3. `%a` and `%{a}` become `(`$\mathcal{A}(a)$`)`; `%(`$\sigma n$`)a` and
   `%(`$\sigma n$`){a}` become `(?P<n>`$\mathcal{A}(a)$`)`, where the prefix
   $\sigma$ is the longest leading run of characters outside
   `[A-Za-z0-9_]` (possibly empty) and $n$ is the rest; `%*a` and `%*{a}`
   become `(?:`$\mathcal{A}(a)$`)`;
4. every other character is copied unchanged.

Replacements are not scanned again. It is a specification error if $a$ is
not in $\mathcal{A}$, if $n$ does not match `[A-Za-z_][A-Za-z0-9_]*`, or if
a `%` followed by `*`, `(` or `{` does not start a complete token. A `%`
followed by anything else (a digit, a space, `)`, the end of the pattern)
stays literal, so `50% done` needs no escaping.

*Example.* $E($`(\w+)=%d %*f %(tag)s`$)$ is
`(\w+)=([+-]?\d+) (?:`$F$`) (?P<tag>\S+)`, where $F$ is the regex of `%f`.
On the line `lr=3 0.5 high`, groups 1, 2 and 3 are `lr`, `3` and `high`, and
group 3 is also named `tag`.

**Lemma A (group numbering).** Let $g(P)$ be the number of capturing groups
that $P$ writes itself, and $t(P)$ the number of capturing alias tokens
(`%a`, `%{a}`, `%(`$\sigma n$`)a`, `%(`$\sigma n$`){a}`) in $P$. Then
$E(P)$ has exactly
$g(P) + t(P)$ capturing groups, numbered in the order in which they start
in $P$.

*Proof.* Rules 1 and 4 copy everything that is not an alias token, so the
$g(P)$ groups of $P$ remain, with escaped parentheses such as `\(` still
escaped. By rule 3, each capturing token is replaced by one capturing group
around $\mathcal{A}(a)$, which has no capturing groups of its own, and
`%*a` and `%%` add none. Replacements are not scanned again, so no other
groups appear. Every replacement sits at the position of its token, so the
order of opening parentheses is the order of the tokens and groups in $P$.
$\square$

**Corner cases.**

* YAML cannot start a plain value with `%`, so quote such patterns:
  `pattern: '%d items'`. Without the quotes, loading fails with a hint.
* A letter after `%` is always an alias: `100%done` expands `%d`, so write
  `100%%done`. The same holds inside a character class: write `[%%d]`.
* `%{2}` is an error (`2` is not an alias name); write `%%{2}` to match
  `%%`.
* `%*(n)a` is an error: a group is either suppressed or named.
* A name may be captured once per pattern and must not repeat a
  `(?P<n>…)` written by hand; otherwise the regex is invalid.
* Every text that `%f` matches is a decimal literal, so `+` never rejects a
  `%f` capture as non-numeric; it can still fail on precision or on
  $\infty + (-\infty)$ (Definition 5).

### Capture bindings

A capture `%(`$\sigma n$`)a` binds the variable $n$ to its own group, with no
entry under `context` or `record`. The prefix $\sigma$ chooses where the
value goes:

| Capture | Binds | Same as |
|---|---|---|
| `%(loss)f` | record variable `loss` | `record: {loss: loss}` |
| `%(=epoch)d` | context variable `epoch`, replaced | `context: {epoch: epoch}` |
| `%(+samples)d` | context variable `samples`, added | `context: {+samples: samples}` |
| `%(@warnings)s` | context variable `warnings`, concatenated | `context: {"@warnings": warnings}` |
| `%(^best)f` | context variable `best`, with a plugin prefix `^` | `context: {"^best": best}` |

Without a prefix the value goes to the record, the way a named capture
becomes a field of the current event in
[grok](https://www.elastic.co/guide/en/logstash/current/plugins-filters-grok.html)
or the [Fluent Bit regex
parser](https://docs.fluentbit.io/manual/pipeline/parsers/regular-expression);
in `zlog` the event is the row. Context carries state across lines, so it is
the one that is marked. A plain replace needs the marker `=`, since its
prefix in `context:` is empty. Plugins cannot register `=` as a prefix, so
it never clashes.

**Definition B (capture bindings).** Let $\Pi$ be the context update
prefixes (`+`, `@` and plugin prefixes) and $\mu(\pi)$ the update of
$\pi \in \Pi$, with $\mu(=) = \mathrm{rep}$. Let a rule have written pattern
$P$ and written bindings $C$ and $B$, and let $\sigma_1 n_1, \dots,
\sigma_k n_k$ be the names of the tokens `%(`$\sigma n$`)a` and
`%(`$\sigma n$`){a}` of $P$, in order, found by the scan of Definition A.
The rule's bindings are

$$C' = \big((n_i, \mu(\sigma_i), n_i) : \sigma_i \ne \varepsilon\big)
\mathbin\Vert C, \qquad
B' = \big((n_i, n_i) : \sigma_i = \varepsilon\big) \mathbin\Vert B,$$

where the source $n_i$ is the group named $n_i$ and $\varepsilon$ is the
empty prefix. It is a specification error if some $\sigma_i \notin
\{\varepsilon, =\} \cup \Pi$. Groups written as `(?P<n>…)` bind nothing.

*Example.* For `epoch %(=epoch)d loss=%(loss)f` with
`record: {event: {value: epoch}}`, $C' = ((\text{epoch}, \mathrm{rep},
\text{epoch}))$ and $B' = ((\text{loss}, \text{loss}), (\text{event},
\texttt{epoch}))$.

**Lemma B (equivalence).** Let $R$ be a rule with pattern $P$ and written
bindings $C$, $B$, and let $R^\circ$ be a rule whose pattern has the same
expansion $E(P)$ but no `%(…)` tokens (it writes `(?P<n>…)` instead), with
written bindings $C'$ and $B'$. Then a specification containing $R$ passes
the checks of Definition 3 exactly when the one containing $R^\circ$ does,
and both produce the same rows on every input.

*Proof.* The semantics below uses a rule only through its regex and its two
binding lists (Definition 1). For $R$ these are $E(P)$, $C'$ and $B'$ by
Definition B. $R^\circ$ has no captures, so Definition B adds nothing, and
its lists are $C'$ and $B'$ as written, with the same regex $E(P)$. Equal
inputs to Definitions 2–8 give equal columns, checks and rows. $\square$

**Corner cases.**

* Every `%(…)` capture binds. A group you only want to reference is written
  as `(?P<n>…)` or referenced by index.
* Explicit bindings may read a captured group: `%(loss)f` with
  `context: {+loss_sum: loss}` gives each row its `loss` and a running sum.
* Binding a variable twice is an error: `%(loss)f` with `record: {loss: 2}`,
  or `%(=x)d %(+x)d` in one rule. `%(=x)d` in one rule and `%(x)d` in
  another make `x` both a context and a record variable (Definition 3).
* Captures come before the written bindings, in pattern order, which fixes
  the column order (Definition 3).
* A capture whose group does not take part in the match binds nothing
  (Definition 2): with `step %(=step)d(?: loss=%(loss)f)?`, the line
  `step 2` leaves `loss` empty.
* A variable name with `.` is not a regex group name, so `%(train.loss)f` is
  an error; write `%f` with `record: {train.loss: 1}`.
* An unknown prefix, as in `%(-x)d` or `%( x)d`, is an error that lists the
  valid ones.
* `reset` may list context variables bound by captures.

## Semantics

Let $I_1,\dots,I_q$ be the inputs in command-line order, where input $I_k$
has path $p_k$ and lines $(\ell_{k,1},\dots,\ell_{k,n_k})$. A line is its
text without the line terminator; `\n`, `\r\n` and `\r` all end a line.
Let $\bot$ denote "no value".

**Definition 1 (rule).** The specification is a sequence of rules
$R_1,\dots,R_m$. Rule $R_j = (P_j, Z_j, C_j, B_j)$ consists of

* a regex $P_j$, the alias expansion $E$ of the written pattern
  (Definition A);
* a reset set $Z_j$: empty without `reset`, the listed names for a list, and
  $\mathcal{C}$ (Definition 3) for `all`;
* context bindings $C_j = ((v_1,\mu_1,s_1),\dots)$, each with a name $v$, an
  update $\mu \in \{\mathrm{rep}, \mathrm{add}, \mathrm{cat}\}$ given by the
  prefix, and a source $s$;
* record bindings $B_j = ((v_1,s_1),\dots)$.

$C_j$ and $B_j$ are the lists $C'$ and $B'$ of Definition B: the capture
bindings, then the written ones.

**Definition 2 (value).** If $P_j$ matches line $\ell$ (leftmost match, as
`re.search`), the value of source $s$ is

$$\operatorname{val}(s) = \begin{cases}
\text{capture of group } g & s \text{ is group } g \text{ and } g \text{ took part in the match} \\
\bot & s \text{ is group } g \text{ and } g \text{ did not take part} \\
t & s \text{ is the constant } t.
\end{cases}$$

*Example.* With $P = $ `v(\d)?`, the line `v` gives $\operatorname{val}(1)=\bot$
and the line `v3` gives $\operatorname{val}(1) = 3$.

**Definition 3 (columns).** Let $\mathcal{C}$ be the context names of
$C_1,\dots,C_m$ and $\mathcal{B}$ the record names of $B_1,\dots,B_m$, each
in order of first appearance without repetition. The header is
$(\texttt{path}) \mathbin\Vert \mathcal{C} \mathbin\Vert \mathcal{B}$. The
specification must satisfy $\mathcal{C} \cap \mathcal{B} = \varnothing$,
$\texttt{path} \notin \mathcal{C} \cup \mathcal{B}$, and every listed reset
name must lie in $\mathcal{C}$. The column name `path` is the setting
`path_column`.

*Example.* In the quick start, $\mathcal{C} = (\text{run}, \text{run\_index},
\text{epoch}, \text{samples}, \text{warnings})$ and $\mathcal{B} =
(\text{event}, \text{loss}, \text{acc})$.

**Definition 4 (selected rule).** For a line $\ell$, the selected rule is the
first rule whose pattern matches:

$$J(\ell) = \min\{\, j : P_j \text{ matches } \ell \,\},$$

undefined if no pattern matches.

*Example.* With rules `loss=%(loss)d` and `acc=%(acc)d`, the line
`acc=2 loss=1` selects rule 1 only, so its row has `loss` but no `acc`.

**Definition 5 (updates).** For a current value $x$ (possibly $\bot$) and a
new value $c$:

$$\mathrm{rep}(x, c) = c, \qquad
\mathrm{cat}(x, c) = \begin{cases} c & x = \bot \\ x \mathbin\Vert s \mathbin\Vert c & \text{otherwise} \end{cases}, \qquad
\mathrm{add}(x, c) = \operatorname{num}(x) + \operatorname{num}(c),$$

with $\operatorname{num}(\bot) = 0$ and $\operatorname{num}(t)$ the decimal
number written by $t$. Addition is exact decimal arithmetic with
`decimal_precision` significant digits. It **fails**, and the run stops, if
either operand is not a number, if the operation is invalid
($\infty + (-\infty)$), or if the exact sum needs more digits than the
precision. The sum is written in fixed-point notation and keeps trailing
zeros.

*Example.* $\mathrm{add}(\bot, \texttt{1e3}) = \texttt{1000}$,
$\mathrm{add}(\texttt{0.1}, \texttt{0.2}) = \texttt{0.3}$ (not
$0.30000000000000004$), $\mathrm{add}(\texttt{0.90}, \texttt{0.10}) =
\texttt{1.00}$, and $\mathrm{add}(\texttt{5}, \texttt{abc})$ stops the run.
NaN propagates: $\mathrm{add}(\texttt{nan}, \texttt{1}) = \texttt{NaN}$.

**Definition 6 (context).** The context is a partial map $\sigma :
\mathcal{C} \rightharpoonup \text{text}$. Each input starts with the empty
map, $\sigma_{k,0} = \varnothing$. For line $\ell = \ell_{k,i}$ with
$j = J(\ell)$ defined, $\sigma_{k,i}$ is obtained from $\sigma_{k,i-1}$ by

1. removing every name in $Z_j$, then
2. for each $(v,\mu,s) \in C_j$ in order with $\operatorname{val}(s) \ne
   \bot$, setting $\sigma(v) \leftarrow \mu(\sigma(v), \operatorname{val}(s))$.

If $J(\ell)$ is undefined, $\sigma_{k,i} = \sigma_{k,i-1}$.

*Example.* With `reset: [n]` and `+n: 1` on the same rule, the line resets
`n` and then adds the capture, so `n` restarts from the captured value.

**Definition 7 (row).** Each line $\ell_{k,i}$ with $j = J(\ell_{k,i})$
defined produces one row $r$:

$$r(\texttt{path}) = p_k, \qquad
r(v) = \sigma_{k,i}(v) \text{ for } v \in \mathcal{C}, \qquad
r(v) = \operatorname{val}(s) \text{ for } (v, s) \in B_j,$$

and every other cell is empty (`null` in JSON). Context updates are applied
before the row is built, so a row sees its own line's updates.

*Example.* The line `processed 150 samples` matches rule 3 of the quick
start. It produces a row even though rule 3 binds only a context variable and
a constant, and that row already shows `samples = 250`.

**Definition 8 (output).** The output is the header followed by the rows of
$I_1$, then those of $I_2$, and so on, each input's rows in line order.

### Properties

Each property follows from the definitions and is checked by the named test.

| # | Property | Test |
|---|---|---|
| P1 | *Persistence.* If no rule updates or resets $v$ on lines $i+1,\dots,k$ of an input, then $\sigma_{k}(v) = \sigma_{i}(v)$. | `test_line_processing.py::test_lemma_persistence_unrelated_lines_keep_context` |
| P2 | *Reset.* If $J(\ell)=j$, $v \in Z_j$ and $C_j$ does not bind $v$, then $v$ is unset after $\ell$. With `reset: all`, the context after $\ell$ depends on $\ell$ alone. | `test_lemma_reset_clears_before_updates` |
| P3 | *File independence.* The rows of $I_k$ depend only on $I_k$, so the output for $(I_1,\dots,I_q)$ equals the header followed by the concatenated rows of separate runs on each $I_k$. A failed multi-file run can be redone for the remaining files alone. | `test_extraction_run.py::test_lemma_file_independence` |
| P4 | *Static header.* The header depends only on the specification, so `zlog` writes it before reading any input and streams rows with memory independent of the log size. | `test_rules.py::test_layout_header_and_arrangement` |
| P5 | *Sum.* If every binding of $v$ uses `+` and $v$ is not reset, then $\sigma(v)$ is the exact sum of the values bound so far, or the run stops; it is never silently rounded. | `test_context_updates.py::test_lemma_sum_folding_add_equals_exact_sum` |
| P6 | *Concatenation.* If every binding of $v$ uses `@` and $v$ is not reset, then $\sigma(v)$ is the values bound so far joined with $s$. | `test_lemma_concatenation_equals_join` |
| P7 | *Counter.* `+n: {value: 1}` on rule $R_j$, with `n` not reset, equals the number of lines of the current input selected by $R_j$ so far (P5 with every value $1$). | `test_lemma_counter_counts_matches` |
| P8 | *Group numbering* (Lemma A). $E(P)$ has $g(P) + t(P)$ groups, in the order they start in $P$. | `test_pattern_aliases.py::test_lemma_group_numbering`, `test_alias_groups_are_numbered_left_to_right` |
| P9 | *No rescanning.* An alias whose regex contains `%` matches that `%` literally. | `test_lemma_expansions_are_not_rescanned` |
| P10 | *Numbers.* Every text `%f` matches is a decimal literal, so `+` never rejects a `%f` capture as non-numeric. | `test_lemma_float_captures_are_addable` |
| P11 | *Capture equivalence* (Lemma B). A rule with captures has the same header and rows as the rule with its bindings written out. The test checks the quick start against its form with positional groups and explicit bindings. | `test_capture_bindings.py::test_lemma_captures_equal_explicit_bindings` |
| P12 | *Bare names.* On the command line, the $k$-th bare `NAME` of a rule reads the $k$-th unnamed group of $E(P)$. | `test_cli_rules.py::test_bare_names_skip_named_groups`, `test_value_sources.py::test_unnamed_group_source_counts_only_unnamed_groups` |

*Example (P3 and P2).* In the quick start, `samples` would carry over from
the adam run into the sgd run without `reset`, because both runs are in one
file. Two separate files would not need the reset: each input starts with an
empty context. `reset: all` would also clear `run_index`, which then would
always be 1, so the example lists the names it clears.

## Output formats

| Format | Shape | Missing value |
|---|---|---|
| `csv` (default) | header row, then one row per matched line; `csv` module quoting | empty cell |
| `json` | an array of objects, one per matched line | `null` |
| `jsonl` | one object per line | `null` |

With `-o FILE`, output goes to a temporary file next to `FILE`, which replaces
`FILE` only when the run succeeds. A failed run leaves an existing `FILE`
untouched. On stdout, rows written before a failure remain.

### Spreadsheet formulas

A spreadsheet may run a cell that starts with `=`, `+`, `-`, `@`, tab,
carriage return, line feed, or their full-width forms as a formula ([OWASP:
CSV Injection](https://owasp.org/www-community/attacks/CSV_Injection)).
`formula_escaping = quote` prefixes such cells with `'`, and `tab` prefixes
them with a tab. It applies to every value, including `path` (so stdin's `-`
becomes `'-`). It is `off` by default, because it changes data: `-0.5` would
become `'-0.5`.

## Configuration

Settings are layered. A later layer overrides an earlier one:

1. built-in defaults
2. `--config file.toml`, table `[zlog]` (see `examples/zlog.toml`)
3. environment variables `ZLOG_<SETTING_NAME>`
4. command-line flags

| Setting | Default | Meaning |
|---|---|---|
| `file_encoding` | `utf-8` | encoding of the inputs (`--encoding`) |
| `decode_errors` | `replace` | codec error handler for the inputs, e.g. `strict` |
| `max_line_length` | `1048576` | longest accepted line in characters; a longer line stops the run |
| `output_format` | `csv` | `csv`, `json`, `jsonl` or a plugin format (`--format`) |
| `output_encoding` | `utf-8` | encoding of the output |
| `csv_delimiter` | `,` | one character other than `"` or a line break (`--csv-delimiter`) |
| `concat_separator` | empty | text between values joined with `@` (`--concat-separator`) |
| `decimal_precision` | `50` | significant digits for `+`, between 1 and 10000 |
| `formula_escaping` | `off` | `off`, `quote` or `tab` (`--formula-escaping`) |
| `path_column` | `path` | name of the input path column |
| `stdin_path` | `-` | value of the path column for stdin |
| `log_level` | `WARNING` | logging level (`--log-level`) |
| `plugins` | `true` | load plugins from entry points |

With `decode_errors = strict`, an undecodable byte stops the run. Text is
decoded in chunks, so the error names the line being read when the bad byte
was found ("at or after line N").

## Errors and exit codes

| Exit code | Cause |
|---|---|
| `0` | success |
| `1` | input error (missing, unreadable or undecodable input, too long a line), invalid value for `+`, or I/O failure |
| `2` | usage, configuration or specification error |

Specifications, settings and inputs are checked before anything is written:
bad group references, unknown or invalid aliases, unknown capture prefixes,
variables bound twice, a non-numeric `+` constant,
unknown output formats and missing inputs all fail without output.

## Plugins and hooks

A plugin is a function registered under the entry point group
`zlog.plugins`. It receives the `PluginRegistry`:

```python
def register(registry):
    registry.register_pattern_alias("ts", r"\d{2}:\d{2}:\d{2}")
    registry.register_context_update("^", lambda settings: MaximumUpdate())
    registry.register_output_format("tsv", lambda stream, settings: ...)
    registry.register_hook(MyHook())
```

* A pattern alias follows the rules of [Pattern aliases](#pattern-aliases);
  an invalid name or regex raises `ValueError`, and the plugin fails to load.
* A context update implements `apply(previous: str | None, value: str) -> str`
  and may raise `zlog.errors.InvalidValueError`. Its prefix must not contain
  letters, digits, `_`, `.`, `:`, `=`, parentheses or whitespace. It works in
  `context:` keys and in captures alike: `^best: 1` or `%(^best)f`.
* An output format is a factory `(stream, settings) -> RowWriter`, where a
  `RowWriter` implements `write_header(columns)`, `write_row(values)` and
  `finish()`.
* A hook implements any of `on_load(spec)`, `on_row(row)` and
  `on_terminate(summary)`. A failing hook is logged and does not stop the
  run.

Set `plugins = false` (or `ZLOG_PLUGINS=off`) to skip loading plugins.

## Migrating from the old format

The earlier `zlog-analyze` aggregated metrics per experiment group and
compared groups statistically. That part is gone; `zlog` now only extracts
rows, and analysis happens downstream (for example with pandas or DuckDB on
the CSV). An old specification is rejected with a pointer to this section.

| Old | New |
|---|---|
| `zlog-analyze SPEC DIR` | `zlog -s SPEC DIR/*/*.out` |
| `patterns: [{regex: R, names: [a, b]}]` | `matches: [{pattern: R, record: {a: 1, b: 2}}]` |
| macros `\f`, `\:`, `\s`, e.g. `accuracy\s\:\s(\f)` | aliases, plain regex: `accuracy\s*[^:]*:\s*%f`; `\s` is the standard regex escape again |
| `macros: {'\i': '\d+'}` used as `(\i)` | `aliases: {i: '\d+'}` used as `%i` (the group is included) |
| `names: [+loss]` (collect a list) | one row per matched line; aggregate downstream |
| `groups:` from directory names | the `path` column, e.g. split `runs/adam-small/0.out` downstream |
| group read from the log text | a context variable |
| `iteration_separator` | a rule on the separator line with `reset: [...]` listing the per-iteration variables, and `+iteration: {value: 1}` to number iterations (`reset: all` would also clear the counter) |
| `--match-policy first/last` | every matched line is a row |
| statistics, plots, reports, checkpoints | removed |

## Development

```sh
.venv/bin/pytest               # tests with branch coverage (≥ 80% enforced)
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src tests       # strict
```
