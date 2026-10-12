"""Descriptive repeated-task measurements, independent of model-quality claims."""

from .errors import ValidationError


def summarize_evaluation(rows):
    """Keep every frozen row in rates, including failed/unattempted repeats.

    A repeat is a run of the same task, not an independent task sample. These
    descriptive counts do not establish statistical significance or live quality.
    Both business metrics and planning checks use missing dimensions as failures.
    """
    if not isinstance(rows, list):
        raise ValidationError("Evaluation summary requires completed case rows")
    seen, groups, dimensions = set(), {}, set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("case_id"), str)
            or not row["case_id"]
            or type(row.get("repeat")) is not int
            or row["repeat"] < 0
            or type(row.get("passed")) is not bool
            or type(row.get("calls")) is not int
            or row["calls"] < 0
        ):
            raise ValidationError("Evaluation summary requires exact bounded case measurements")
        key = (row["case_id"], row["repeat"])
        if key in seen:
            raise ValidationError("Evaluation summary cannot count duplicate repeats")
        seen.add(key)
        fields = {}
        for name in ("checks", "metrics"):
            values = row.get(name, {})
            if (
                not isinstance(values, dict)
                or any(not isinstance(k, str) or type(v) is not bool for k, v in values.items())
                or fields.keys() & values.keys()
            ):
                raise ValidationError("Evaluation dimensions require distinct boolean measurements")
            fields.update(values)
        dimensions.update(fields)
        groups.setdefault(row["case_id"], []).append((row, fields))

    def counts(group):
        total = len(group)
        passed = sum(row["passed"] for row, _ in group)
        return {
            "total": total,
            "passed": passed,
            "attempted": sum(row["calls"] > 0 for row, _ in group),
            "calls": sum(row["calls"] for row, _ in group),
            "pass_rate": passed / total if total else None,
        }

    all_rows = [item for group in groups.values() for item in group]
    result = counts(all_rows)
    per_case = {}
    for name, group in groups.items():
        value = counts(group)
        value["all_repeats_passed"] = value["passed"] == value["total"]
        value["mixed_outcomes"] = 0 < value["passed"] < value["total"]
        per_case[name] = value
    result.update(
        per_case=per_case,
        repeated_case_count=sum(v["total"] > 1 for v in per_case.values()),
        all_repeats_passed_count=sum(v["all_repeats_passed"] for v in per_case.values()),
        mixed_outcome_case_count=sum(v["mixed_outcomes"] for v in per_case.values()),
        dimensions={},
    )
    for name in sorted(dimensions):
        passed = sum(fields.get(name) is True for _, fields in all_rows)
        result["dimensions"][name] = {
            "passed": passed,
            "total": len(rows),
            "rate": passed / len(rows),
        }
    return result
