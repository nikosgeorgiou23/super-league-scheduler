> This document records a standalone analysis. Relative artifact paths refer to the original local directory outputs/bound-lambda5-no-opponent-limit-20261023/. The full certificates and verification scripts are not included in Git; this repository publishes the proof text and numerical summary.

# Certified upper bound for lambda = 5 after removing the opponent-streak restriction

## Instance and conclusion

This analysis concerns the current repository rules, 14 teams, 26 rounds, seven
matches per round, eight available slots, data seed `20261019`, and coefficient
scale $K=10^4$. The snapshot is in `instance/`. The attractiveness values are
identical to those used in the previous lambda=3 and lambda=7 analyses.

**There is no restriction on consecutive opponents from the four highest-strength
teams.** The maximum of two consecutive home matches or two consecutive away
matches remains in force. These are different restrictions.

The strongest bound certified in this computation is

$$
\boxed{F_5^\star\le 1385581},\qquad
\boxed{F_5^\star/K\le 138.5581}.
$$

This is a valid global upper bound for the current enlarged feasible set. It is
not a claim that the bound is attainable, that the optimum has been found, or
that no stronger bounding method exists. Bounds obtained with the removed
restriction were not reused as certificates for the new instance.

## 1. Objective and numerical conventions

For a feasible season $S$, define

$$
U_r(S)=\sum_{(h,a,s)\in S_r}(a_{h,r}+a_{a,r})V_s,
\qquad Z_5(S)=\sum_{r=1}^{26}U_r(S)-5(\max_rU_r(S)-\min_rU_r(S)).
$$

The solver actually maximizes the integer objective

$$
C_{r,h,a,s}=\operatorname{round}(K(a_{h,r}+a_{a,r})V_s),\quad
q_r(S)=\sum_{(h,a,s)\in S_r}C_{r,h,a,s},
$$

$$
F_5(S)=\sum_rq_r(S)-5(\max_rq_r(S)-\min_rq_r(S)).
$$

The coefficient generation reproduces Python's actual floating-point operations
and ties-to-even rounding. Statements about $F_5$ and $Z_5$ are distinguished.

## 2. Analytical bound by rearrangement

Every team appears once per round. Ignoring opponent, venue, and geographical
restrictions, the seven largest slot weights can be assigned to the fourteen
team appearances. In descending order, the repeated weights are

$$w=(1,1,.9,.9,.8,.8,.7,.7,.6,.6,.5,.5,.4,.4).$$

If $a_{(i),r}$ denotes descending attractiveness, the rearrangement inequality gives

$$U_r\le b_r:=\sum_{i=1}^{14}a_{(i),r}w_i.$$

Indeed, swapping a reversed pair changes the sum by
$(a_i-a_j)(w_i-w_j)\ge0$. Repeated swaps give the descending assignment.
Nonnegative attractiveness ensures that replacing any chosen lower slot weight
by an available higher one cannot decrease this relaxed upper bound.

Let $T$ contain the five rounds with largest $b_r$. Then

$$
\begin{aligned}
Z_5
&=\sum_{r\notin T}U_r+\sum_{r\in T}U_r-5U_{\max}+5U_{\min}\\
&\le\sum_{r\notin T}b_r+5\min_rb_r,
\end{aligned}
$$

because $\sum_{r\in T}U_r\le5U_{\max}$ and $U_{\min}\le\min_rb_r$.
Here $T=\{6,18,22,24,25\}$ and this real-valued bound is
$140.93286520777033$ (displayed decimal).

For a rigorous bound on the coded integer objective, regard each stored input
float as its exact binary rational value and compute

$$e_r=\max_{h<a,s}\{C_{r,h,a,s}-K(a_{h,r}+a_{a,r})V_s\},\qquad
B_r=\lfloor Kb_r+7e_r\rfloor.$$

There are exactly seven selected coefficients per round, so $q_r\le B_r$.
All $e_r$, $B_r$, and their exact-rational derivation are reproducible from
`analyze_bound.py` and `analytical.json`. Applying the same five-round argument
gives the integer upper bound $1,409,408$.

## 3. Linear relaxations and valid inequalities

Two continuous relaxations were constructed. In the aggregate model, each
unordered pair and slot has one variable in $[0,1]$. It retains team participation,
slot capacities, each pair once per half, no immediate pair rematch in rounds
13 and 14, round-value equalities, the bounds $B_r$, and highest/lowest envelopes.
Home orientation, venue balance, home/away streaks, and geography are relaxed.
Any feasible season embeds by summing its two oriented alternatives.

The full relaxation retains home orientation, reverse venues, geographical home
conflicts, and the home/away streak inequalities as well. It has 37,884 variables
and 1,842 initial rows. The aggregate relaxation has 18,956 variables and 923
initial rows. Neither model contains the deleted opponent-streak inequalities.

For each round and odd team subset $W$, the matching inequality

$$\sum_{\{h,a\}\subseteq W,s}x_{r,h,a,s}\le (|W|-1)/2$$

is valid: an internal matching consumes two distinct teams per selected edge.
Odd subsets of sizes 3, 5, and 7 were separated. Larger odd subsets are covered
by their complements and the participation equalities for a perfect matching.

Additional inequalities were obtained from a conflict graph. Vertex $(r,p)$
means unordered pair $p$ plays in round $r$. Adjacent vertices cannot both be
selected: they share a team in one round, repeat one pair within a half, or
repeat that pair across rounds 13 and 14. For an odd closed walk of length $L$,
sum the $L$ edge inequalities $x_i+x_{i+1}\le1$. Integrality gives

$$\sum_{i=1}^Lx_i\le\lfloor L/2\rfloor.$$

Multiplicity is retained if a vertex occurs more than once. A total of 82 such
cuts were added, and `verify_graph.py` checks their combinatorial validity.

## 4. Exact arithmetic certification of LP bounds

Write any relaxation as $\max g^Tx$, with rows $A_ix\le b_i$ or $A_ix=b_i$
and variable bounds $0\le x_j\le u_j$. Set $Q=10^{12}$. Choose integer
multipliers $p_i\ge0$ for inequality rows and arbitrary signed integer multipliers
for equality rows. Rounded floating-point dual values are only a way to choose
these integers; their optimality or numerical accuracy is not assumed.

Define

$$\beta=\sum_ip_ib_i,\qquad d_j=Qg_j-\sum_ip_iA_{ij}.$$

For every feasible $x$,

$$Qg^Tx=\sum_ip_iA_ix+\sum_jd_jx_j
\le\beta+\sum_ju_j\max(0,d_j).$$

Consequently, since the season's objective is integer,

$$F_5^\star\le\left\lfloor
\frac{\beta+\sum_ju_j\max(0,d_j)}{Q}\right\rfloor.$$

This proof uses integer arithmetic and explicit residual correction. GLOP
tolerances cannot invalidate the resulting certificate. The compressed
certificates store all rows, multipliers, objective coefficients and variable
bounds. `verify_certificate.py` checks the arithmetic and source hashes;
`verify_model.py` independently reconstructs the base rows, odd-set rows,
coefficient bounds, and objective from the current instance. In particular it
asserts that no deleted opponent-streak row is present.

## 5. Integer per-round pricing

The previous bound maximizes every residual variable independently over a box.
A tighter bound groups residuals by round. Eliminate each $q_r$ using its exact
value equality. For a local match-slot variable $y_k$ in round $r$, put

$$w_k=d_{y_k}+d_{q_r}C_k.$$

Let $\mathcal P_r$ be the finite set of integral one-round schedules satisfying
participation, slot capacity, geographical home conflicts, and $q_r\le B_r$.
Every feasible season restricts to an element of $\mathcal P_r$. Cross-round
requirements remain represented by the dual terms; dropping any remaining
cross-round coupling only enlarges the residual maximization domain.

Use $D=10^6$ and outward-round $c_k=\lceil w_k/D\rceil$. Because $y_k\ge0$,
$\sum_kw_ky_k\le D\sum_kc_ky_k$. If

$$L_r=\max_{y\in\mathcal P_r}\sum_kc_ky_k,$$

and $H$ is the box bound for the highest/lowest residuals, then

$$QF_5^\star\le\beta+H+D\sum_{r=1}^{26}L_r.$$

All 26 local models were solved to `OPTIMAL`. The independent pricing verifier
reconstructs their variables, objective, and every constraint, solves them again
with one worker, and checks the bound arithmetic.

For the certificate giving the reported bound:

$$\begin{aligned}
\beta&=1385586120241550889,\\
H&=0,\\
\sum_rL_r&=-4386824,\\
\beta+H+D\sum_rL_r&=1385581733417550889.
\end{aligned}$$

Division by $10^{12}$ and flooring proves the claimed integer upper bound.
The model files and certificates are saved, so this is an auditable global bound
rather than a heuristic estimate.

## 6. Bounds obtained and incumbent gap

| Method | Integer bound divided by $K$ |
|---|---:|
| Sum of analytical round caps | 144.5069 |
| Analytical bound including range penalty | 140.9408 |
| Aggregate LP | 138.5702 |
| Aggregate LP + odd sets | 138.5587 |
| Aggregate LP + odd sets + conflict cuts | 138.5583 |
| Integer pricing from conflict LP | 138.5582 |
| Full LP | 138.5701 |
| Full LP + odd sets | 138.5586 |
| Integer pricing from full LP | 138.5581 |

Fifteen stored schedules were checked against the current rules and re-evaluated
with lambda=5 on this same attractiveness scenario. The best of those has

$$F_5(S)=1,363,999,\qquad F_5(S)/K=136.3999.$$

It was originally found in `outputs/bound-analysis-20261022/integer_candidate.json`;
this analysis does not claim a new optimization run produced it. Its current-rule
validation and an exported copy are saved alongside the proof.

Therefore

$$\boxed{136.3999\le F_5^\star/K\le 138.5581}.$$

Using the incumbent in the denominator, the certified relative gap is

$$\frac{138.5581-136.3999}{136.3999}\,100=1.58225922\%.$$

Using the upper bound in the denominator gives 1.55761374%. The incumbent is
guaranteed to attain at least 98.44238626% of the optimal positive integer objective.
Neither percentage is the unknown exact distance from the true optimum.

## 7. Bound for the unrounded objective

Enumeration with exact binary-rational inputs checks all match-slot coefficients
and establishes $|C_k-K(a_h+a_a)V_s|\le1/2$ for this instance. Thus
$|q_r-KU_r|\le7/2$ for each round. The total error is at most $26(7/2)=91$;
the range error is at most $7$, since maximum and minimum are each Lipschitz
with constant one in the sup norm. Hence

$$|F_5/K-Z_5|\le\frac{91+5\cdot7}{10000}=0.0126.$$

The conservative bound for the exact unrounded mathematical objective is

$$\boxed{Z_5^\star\le 138.5707}.$$

The incumbent's unrounded value is $136.39939353940045$, giving a conservative
unrounded-objective gap of 1.59187398%. The sharper 138.5581 bound concerns
the rounded integer objective actually optimized by the program.

## Reproduction

Use the repository virtual environment. From the repository root, run
`analyze_bound.py`, optionally with `--full`, then `graph_cuts.py`, and
`price_rounds.py --graph`. All paths below refer to this proof's directory.
Run `verify_certificate.py` for each certificate directory (`.`, `graph`, `full`),
`verify_model.py` for those same directories, `verify_graph.py`, and
`verify_pricing.py` (or `--full` for full-relaxation pricing).
The saved `instance/` snapshot fixes the problem being certified. Verification
JSON files record the actual checks from this computation; `summary.json`
contains the machine-readable numerical results. Analysis files are under the
repository's ignored `outputs/` directory; solver implementation and root
documentation were not modified by this calculation.
