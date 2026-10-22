import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/**
 * AIChart — grafik jawaban AI (Fix #18C, Recharts).
 *
 * Read-only: data dikirim backend (`chart_data`) dan hanya dirender, tanpa
 * interaksi tulis. Data kosong → tidak merender apa pun.
 */

export interface AIChartPoint {
  label: string;
  value: number;
}

interface AIChartProps {
  type: "line" | "bar";
  data: AIChartPoint[];
  title?: string;
  unit?: string;
}

export function AIChart({ type, data, title, unit }: AIChartProps) {
  if (!data || data.length === 0) return null;

  const isLine = type === "line";

  return (
    <div className="my-3" data-testid="ai-chart">
      {title ? <p className="mb-2 text-sm font-medium">{title}</p> : null}
      <div className="h-[140px] w-full text-accent-blue">
        <ResponsiveContainer width="100%" height="100%">
          {isLine ? (
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" fontSize={12} />
              <YAxis fontSize={12} />
              <Tooltip formatter={(value) => `${String(value)}${unit ?? ""}`} />
              <Line type="monotone" dataKey="value" stroke="currentColor" dot={false} />
            </LineChart>
          ) : (
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" fontSize={12} />
              <YAxis fontSize={12} />
              <Tooltip formatter={(value) => `${String(value)}${unit ?? ""}`} />
              <Bar dataKey="value" fill="currentColor" />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
