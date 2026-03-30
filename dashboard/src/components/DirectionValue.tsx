interface Props {
  value: number;
  suffix?: string;
  precision?: number;
  className?: string;
}

export default function DirectionValue({
  value,
  suffix = "",
  precision = 2,
  className = "",
}: Props) {
  const direction = value > 0 ? "up" : value < 0 ? "down" : "flat";
  const arrow = value > 0 ? "▲" : value < 0 ? "▼" : "•";
  const formatted = `${value > 0 ? "+" : ""}${value.toFixed(precision)}${suffix}`;

  return (
    <span className={`direction-value is-${direction} ${className}`.trim()}>
      <span className="direction-value-arrow">{arrow}</span>
      <span className="direction-value-text">{formatted}</span>
    </span>
  );
}
