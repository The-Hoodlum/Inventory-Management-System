// Forecast API calls, built on the shared request layer.
import { api } from "@/lib/api";

export interface ForecastOut {
  id: string;
  product_id: string;
  warehouse_id: string;
  method: string;
  window_days: number;
  horizon_days: number;
  forecast_date: string;
  daily_demand: string;
  adjusted_daily_demand: string;
  std_dev_daily: string;
  confidence: string;
  risk_score: string;
  observations: number;
  days_with_demand: number;
  total_demand: string;
  generated_at: string;
}

export interface ForecastSummary {
  total_forecasts: number;
  pairs_forecasted: number;
  avg_confidence: string | null;
  avg_risk_score: string | null;
  high_risk_count: number;
  by_method: Record<string, number>;
  recent: ForecastOut[];
  generated_at: string;
}

export interface ForecastProvider {
  key: string;
  label: string;
}

export interface DemandPattern {
  product_id: string;
  warehouse_id: string;
  window_days: number;
  as_of: string;
  observations: number;
  days_with_demand: number;
  adi: string | null;
  cv_squared: string | null;
  classification: string;
  trend_direction: string;
  trend_slope: string;
  trend_strength: string;
  seasonal: boolean;
  seasonal_period: number | null;
  seasonal_strength: string;
  suggested_demand_type: string | null;
  suggested_method: string;
  drivers: string[];
}

export interface RunForecastBody {
  warehouse_id: string;
  product_id?: string;
  method?: string; // provider key or "auto"
  window_days?: number;
  horizon_days?: number;
}

export interface RunForecastResponse {
  method: string;
  warehouse_id: string;
  generated: number;
  forecasts: ForecastOut[];
}

export const forecastApi = {
  summary: () => api.get<ForecastSummary>("/forecast/summary"),
  providers: () => api.get<ForecastProvider[]>("/forecast/providers"),
  run: (body: RunForecastBody) => api.post<RunForecastResponse>("/forecast/run", body),
  analyze: (body: { product_id: string; warehouse_id: string; window_days?: number }) =>
    api.post<DemandPattern>("/forecast/analyze", body),
};
