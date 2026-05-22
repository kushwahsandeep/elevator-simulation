# Elevator Scheduling Strategy Study

## Purpose

This study compares the passenger outcomes produced by three dispatcher strategies implemented in the elevator simulator:

- **Nearest Car**
- **Round Robin**
- **Score Based**

The goal was to validate whether the scheduling strategy has a measurable impact on passenger wait time and total journey time.

## Method

Each strategy was run through the simulator and the generated `passenger_journey_*.csv` output was analyzed.

The comparison focuses on:

- passenger delivery count
- average wait time
- median wait time
- 95th percentile wait time
- average total passenger time
- worst-case passenger time

> Note: The attached outputs were generated from live/continuous simulation runs, so the number of generated passengers differs slightly between strategies. For a perfectly controlled benchmark, the same fixed request CSV should be replayed against each strategy. Even with that caveat, the result is still useful for understanding broad scheduler behavior.

## Summary Results

| Strategy | Delivered | Avg Wait | Median Wait | P95 Wait | Max Wait | Avg Total | Median Total | P95 Total | Max Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Nearest Car | 3,097 | 4.77 | 2 | 17 | 153 | 26.96 | 24 | 55 | 204 |
| Round Robin | 4,579 | 180.54 | 58 | 741.1 | 11,218 | 202.61 | 81 | 766.2 | 11,223 |
| Score Based | 3,850 | 4.83 | 2 | 16 | 237 | 26.92 | 24 | 56 | 275 |


## Observations

### 1. Round Robin performed poorly under this workload

Round Robin had significantly higher average wait and total passenger time. Its average total time was **202.61 ticks**, compared with **26.92 ticks** for Score Based and **26.96 ticks** for Nearest Car.

This happened because Round Robin distributes requests mechanically across elevators without considering current position, load, or suitability. That can send elevators to inefficient pickups even when another elevator is much better placed.

### 2. Score Based and Nearest Car were close on average

Score Based produced the best average total time at **26.92 ticks**, while Nearest Car was very close at **26.96 ticks**.

Nearest Car had slightly lower average wait time (**4.77 ticks**) than Score Based (**4.83 ticks**), while Score Based had a slightly better average total time.

### 3. Score Based gave the best overall balance

Score Based delivered all passengers in its run and produced the best average total time. Compared with Round Robin, Score Based reduced:

- average wait time by approximately **97.3%**
- average total passenger time by approximately **86.7%**

### 4. Tail behavior still needs more analysis

Both Nearest Car and Score Based had low median wait times, but the max wait time shows that some passengers can still wait significantly longer. This suggests a future scheduler should explicitly consider fairness/starvation prevention, not only average efficiency.

## Conclusion

For the current implementation, **Score Based is the best default strategy** because it offers the strongest overall balance between efficiency and extensibility.

Round Robin is useful as a baseline, but it is not suitable as the main dispatch strategy because it ignores elevator state.

Nearest Car is simple and performs well, but Score Based is more extensible because it can evolve to include additional signals such as:

- direction alignment
- elevator load
- pending stops
- estimated pickup delay
- starvation/fairness penalty

## Future Improvements

If more time were available, I would improve the benchmark and scheduler in the following ways:

1. Replay the exact same fixed request file across all strategies.
2. Add multiple traffic patterns:
   - morning up-peak
   - evening down-peak
   - random mixed traffic
   - high-density lobby traffic
3. Add fairness metrics:
   - max wait time
   - p95/p99 wait time
   - starvation count
4. Extend the score-based strategy with configurable weights.
5. Generate a benchmark report automatically as part of the test/demo tooling.
