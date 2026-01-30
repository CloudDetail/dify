from dataclasses import dataclass, field
from typing import Any, Optional

import requests
from pydantic import ValidationError

from configs import dify_config

ProviderPriority = ["apo", "prometheusmetric"]  # 优先分析 apo / prometheus 的返回结果
ProviderPriorityIndex = {v: i for i, v in enumerate(ProviderPriority)}  # 优化索引查找


@dataclass
class QueryMetricResult:
    type: str = "metric"
    display: bool = True
    unit: str = ""
    data: dict[str, list] = field(default_factory=dict)


def query_metric(
    metric_name: str,
    start_time: Any,
    end_time: Any,
    step: int,
    labels: Optional[dict[str, str]] = None,
    compare: Optional[list[str]] = None,
) -> QueryMetricResult:
    """
    根据配置查询指标，统一返回 QueryResult 对象。

    Args:
        metric_name: 指标名
        start_time: 查询起始时间（时间戳）
        end_time: 查询结束时间（时间戳）
        step: 查询步长（秒）
        labels: 可选标签过滤
        compare: 可选对比维度（仅 dataplane 生效）

    Returns:
        QueryResult 对象
    """

    labels = labels or {}
    compare = compare or []

    try:
        start_ts = to_int(start_time)
        end_ts = to_int(end_time)

        if dify_config.DATA_SOURCE == "dataplane":
            # 调用 dataplane 查询
            return __query_metric_by_dataplane(
                metric_name=metric_name,
                start_ts=start_ts,
                end_ts=end_ts,
                step=step,
                labels=labels,
                compare=compare,
            )

        # 调用 APO 查询
        return __query_metric_by_apo(
            metric_name=metric_name,
            start_ts=start_ts,
            end_ts=end_ts,
            step=step,
            labels=labels,
        )

    except Exception as e:
        # 捕获异常，返回空 QueryResult 或自定义错误处理
        print(f"Error querying metric {metric_name} by {dify_config.DATA_SOURCE}: {e}")
        return QueryMetricResult(
            type="metric",
            display=True,
            unit="",
            data={"timeseries": []},
        )


from typing import Optional

from pydantic import BaseModel, Field


class QueryMetricsRequest(BaseModel):
    providerId: int = Field(..., description="接入数据源ID")
    startTime: int = Field(..., description="开始时间")
    endTime: int = Field(..., description="结束时间")
    metric: str = Field(..., description="指标名，如 http_requests_total")
    labels: Optional[dict[str, str]] = Field(default=None, description='维度标签，如 {"service": "svc-a"}')
    step: Optional[int] = Field(default=None, description="步长")
    compare: Optional[list[str]] = Field(
        default=None, description='可选值：["dayOverDay", "weekOverDay"]，是否统计日同比和周同比'
    )


class ChartData(BaseModel):
    chartData: dict[str, float]  # 时间戳（字符串）到指标值的映射？确认有序性
    # value: Optional[Any] = None              # 平均值
    # ratio: dict[str, Optional[Any]] = {}     # {"dayOverDay": None, "weekOverDay": None}

    def avg_value(self) -> float:
        """
        计算图表数据的平均值
        """
        vals = [v for v in self.chartData.values() if v is not None]
        if not vals:
            return 0.0
        return sum(vals) / len(vals)

    def avg_spike(self) -> float:
        """将原表数据按时间分成上下两部分,分别计算平均值, 返回平均值的突变比例"""
        sorted_items = list(self.chartData.items())  # 或者 sorted(self.chartData.items(), key=lambda x: x[0])
        mid = len(sorted_items) // 2

        # 前半段平均值
        first_vals = [v for _, v in sorted_items[:mid] if v is not None]
        avg_first = sum(first_vals) / len(first_vals) if first_vals else 0.0

        # 后半段平均值
        second_vals = [v for _, v in sorted_items[mid:] if v is not None]
        avg_second = sum(second_vals) / len(second_vals) if second_vals else 0.0

        # 避免除零
        if avg_first == 0.0:
            return float("inf") if avg_second != 0 else 0.0

        return (avg_second - avg_first) / avg_first


class TimeSeries(BaseModel):
    legend: str  # 图例（pod:container 格式）
    legendFormat: str  # 图例格式（固定 "{{pod}}: {{ container }}"）
    labels: dict[str, str]  # 标签（pod、container 等）
    chart: ChartData  # 图表数据


class MetricResult(BaseModel):
    title: str  # 指标名称
    unit: str  # 单位（如 "core"）
    timeseries: list[TimeSeries] = Field(default_factory=list)  # 时间序列数组


class MetricResults(BaseModel):
    metrics: list[MetricResult] = Field(default_factory=list)


class MetricResponse(BaseModel):
    msg: str  # 空字符串，保持格式一致
    result: MetricResult  # 核心数据部分
    # success 字段根据需要可加


class QueryMetricsResult(BaseModel):
    providerId: int  # 接入数据源 ID
    clusterId: str  # 集群 ID
    dataSource: str  # 数据源名称
    metrics: Optional[MetricResponse] = None  # 核心指标结果
    error: Optional[str] = None  # 错误信息，可为空


class QueryMetricsResponse(BaseModel):
    data: list[QueryMetricsResult]


def __query_metric_by_dataplane(
    metric_name: str,
    start_ts: int,
    end_ts: int,
    step: int,
    labels: dict[str, str],
    compare: list[str],
) -> QueryMetricResult:
    """
    Query metric by dataplane

    Args:
        metric_name (str): metric name
        start_ts (int): start timestamp in microseconds
        end_ts (int): end timestamp in microseconds
        step (int): step
        labels (Optional[dict[str, str]]): labels
        compare (Optional[list[str]]): compare,options: ["dayOverDay", "weekOverDay"]

    Returns:
        Optional[query_result]: query result
    """
    try:
        url = f"{dify_config.DATAPLANE_URL}/datasource/queryMetrics"
        req = QueryMetricsRequest(
            providerId=0,
            metric=metric_name,
            labels=labels,
            startTime=start_ts,
            endTime=end_ts,
            step=step,
            compare=compare,
        )

        resp = requests.post(url, json=req.model_dump())
        resp.raise_for_status()

        data = resp.json()
        if error := data.get("error"):
            print(f"Error querying metric: {error}")
            return QueryMetricResult(type="metric", display=True, unit="", data={"timeseries": []})
        mr = QueryMetricsResponse.model_validate(data)
        return __convert_metric_results(mr)
    except requests.RequestException as e:
        print(f"HTTP request failed: {e}")
    except ValidationError as e:
        print(f"Response validation failed: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

    return QueryMetricResult(type="metric", display=True, unit="", data={"timeseries": []})


def __convert_metric_results(
    metric_response: QueryMetricsResponse,
) -> QueryMetricResult:
    if not metric_response.data:
        return QueryMetricResult(type="metric", display=True, unit="", data={"timeseries": []})

    # TODO merge different metric results' timeseries, need to ensure unit consistency
    metricResult = __select_highest_priority_result(metric_response)
    if metricResult is None:
        return QueryMetricResult(type="metric", display=True, unit="", data={"timeseries": []})

    if metricResult.error or not metricResult.metrics or not metricResult.metrics.result.timeseries:
        return QueryMetricResult(type="metric", display=True, unit="", data={"timeseries": []})

    mr = metricResult.metrics.result
    return QueryMetricResult(
        type="metric",
        display=True,
        unit=mr.unit,
        data={"timeseries": [m.model_dump() for m in mr.timeseries]},
    )


def __select_highest_priority_result(results: QueryMetricsResponse) -> Optional[QueryMetricsResult]:
    """从多个数据源中选择优先级最高的数据源结果"""
    if not results or not results.data:
        return None

    best_result = None
    for res in results.data:
        if not res.metrics or not res.metrics.result.timeseries:
            continue

        if not best_result:
            best_result = res
            continue
        else:
            best_priority = ProviderPriorityIndex.get(best_result.dataSource, float("inf"))
            current_priority = ProviderPriorityIndex.get(res.dataSource, float("inf"))
            if current_priority < best_priority:
                best_result = res
    return best_result


def __query_metric_by_apo(
    metric_name: str,
    start_ts: int,
    end_ts: int,
    step: int,
    labels: dict[str, str],
) -> QueryMetricResult:
    reqBody = {
        "metricName": metric_name,
        "params": labels or {},
        "startTime": start_ts,
        "endTime": end_ts,
        "step": step,
    }

    resp = requests.post(dify_config.APO_BACKEND_URL + "/api/metric/query", json=reqBody)
    list = resp.json()["result"]
    return QueryMetricResult(
        type="metric",
        display=True,
        unit=list["unit"],
        data={"timeseries": list["timeseries"]},
    )


def to_int(value: Any, default: Optional[int] = None) -> int:
    if isinstance(value, int):
        return value
    if value is None:
        if default is not None:
            return default
        raise ValueError("Cannot convert None to int")
    try:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                if default is not None:
                    return default
                raise ValueError("Empty string cannot be converted to int")
            if "." in value:
                return int(float(value))
        return int(value)
    except (ValueError, TypeError):
        if default is not None:
            return default
        raise


class QueryServiceRedChartsResponse(BaseModel):
    msg: str
    results: list[MetricResult] = Field(default_factory=list)


def query_red_metrics(
    title: str,
    service: str,
    cluster: str,
    start_time: Any,
    end_time: Any,
    endpoint: str,
) -> QueryMetricResult:
    """

    Args:
        title (str): Options: ["Response Time","Error Rate","Tpm","Success Rate"]
        service (str): service_name
        cluster (str): cluster
        start_time (Any): start_ts in microseconds
        end_time (Any): end_ts in microseconds
        endpoint (str): content_key

    Returns:
        QueryMetricResult: metric result
    """
    start_ts = to_int(start_time)
    end_ts = to_int(end_time)

    request_params = {"service": service, "cluster": "", "startTime": start_ts, "endTime": end_ts, "endpoint": endpoint}

    resp = requests.get(
        f"{dify_config.DATAPLANE_URL}/dataplane/redcharts",
        params=request_params,
        timeout=10,
    )
    resp.raise_for_status()

    data = resp.json()
    if error := data.get("error"):
        print(f"Error querying metric: {error}")
        return QueryMetricResult(type="metric", display=True, unit="", data={"timeseries": []})
    mr = QueryServiceRedChartsResponse.model_validate(data)
    return __convert_red_results(title, mr)


def __convert_red_results(
    title: str,
    metric_response: QueryServiceRedChartsResponse,
) -> QueryMetricResult:
    if not metric_response.results:
        return QueryMetricResult(type="metric", display=True, unit="", data={"timeseries": []})

    for metric in metric_response.results:
        if metric.title == title:
            return QueryMetricResult(
                type="metric",
                display=True,
                unit=metric.unit,
                data={"timeseries": [m.model_dump() for m in metric.timeseries]},
            )
        elif metric.title == "Error Rate" and title == "Success Rate":
            return __error_rate_to_success_rate(metric)

    return QueryMetricResult(type="metric", display=True, unit="", data={"timeseries": []})


def __error_rate_to_success_rate(error_rate: MetricResult) -> QueryMetricResult:
    for ts in error_rate.timeseries:
        for key, value in ts.chart.chartData.items():
            ts.chart.chartData[key] = round((100 - value) / 100, 2)

    return QueryMetricResult(
        type="metric",
        display=True,
        unit="percentunit",
        data={"timeseries": [m.model_dump() for m in error_rate.timeseries]},
    )
