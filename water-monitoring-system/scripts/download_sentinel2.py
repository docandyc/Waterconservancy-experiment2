"""
Sentinel-2 L2A 月度数据批量下载脚本 (仅下载 B3 + B11 波段)
目标: 官厅水库 2024年 每月云量最低的一景
仅下载 B3 (10m, ~100MB) 和 B11 (20m, ~30MB)
"""

import os
import sys
import json
import time
import requests

# ============================================================
# 配置
# ============================================================
USERNAME = "tls14nice@outlook.com"
PASSWORD = "X159592619zxc!"

OUTPUT_DIR = "/Users/tls/code/水利信息/EXP3/raw_sentinel2"
YEAR = 2024

ROI_WKT = "POLYGON((115.43 40.18,115.93 40.18,115.93 40.40,115.43 40.40,115.43 40.18))"
MAX_CLOUD = 30.0

CATALOGUE_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
ZIPPER_URL = "https://zipper.dataspace.copernicus.eu/odata/v1/Products"


# ============================================================
# 认证
# ============================================================
_token_cache = {"token": None, "expires": 0}

def get_access_token():
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires"]:
        return _token_cache["token"]
    resp = requests.post(TOKEN_URL, data={
        "client_id": "cdse-public",
        "username": USERNAME,
        "password": PASSWORD,
        "grant_type": "password"
    })
    resp.raise_for_status()
    token = resp.json()["access_token"]
    _token_cache["token"] = token
    _token_cache["expires"] = now + 540  # 9 min
    return token


# ============================================================
# 搜索产品
# ============================================================
def search_monthly(year, month):
    start = f"{year}-{month:02d}-01T00:00:00.000Z"
    if month == 12:
        end = f"{year+1}-01-01T00:00:00.000Z"
    else:
        end = f"{year}-{month+1:02d}-01T00:00:00.000Z"

    filter_str = (
        f"Collection/Name eq 'SENTINEL-2' and "
        f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq 'S2MSI2A') and "
        f"OData.CSC.Intersects(area=geography'SRID=4326;{ROI_WKT}') and "
        f"ContentDate/Start ge {start} and "
        f"ContentDate/Start lt {end} and "
        f"Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' and att/OData.CSC.DoubleAttribute/Value le {MAX_CLOUD})"
    )

    params = {"$filter": filter_str, "$top": 20}
    resp = requests.get(CATALOGUE_URL, params=params)
    if resp.status_code != 200:
        print(f"  [搜索错误] HTTP {resp.status_code}")
        return []

    products = resp.json().get("value", [])

    for p in products:
        cloud = 100.0
        for a in p.get("Attributes", []):
            if a.get("Name") == "cloudCover":
                cloud = float(a.get("Value", 100))
                break
        p["_cloud"] = cloud

    products.sort(key=lambda x: x["_cloud"])
    return products


# ============================================================
# 下载单个波段文件
# ============================================================
def download_band_file(product_id, safe_name, granule_name, band_folder, band_filename, output_path):
    """通过 Nodes API 下载单个波段文件"""
    token = get_access_token()

    url = (
        f"{ZIPPER_URL}({product_id})/Nodes({safe_name})/Nodes(GRANULE)"
        f"/Nodes({granule_name})/Nodes(IMG_DATA)/Nodes({band_folder})"
        f"/Nodes({band_filename})/$value"
    )

    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, stream=True, allow_redirects=True, timeout=60)

    if resp.status_code == 401:
        _token_cache["token"] = None
        token = get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(url, headers=headers, stream=True, allow_redirects=True, timeout=60)

    if resp.status_code != 200:
        print(f"    [错误] HTTP {resp.status_code} 下载 {band_filename}", flush=True)
        return False

    total = int(resp.headers.get("Content-Length", 0))
    downloaded = 0
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=131072):
            f.write(chunk)
            downloaded += len(chunk)

    size_mb = downloaded / 1024 / 1024
    print(f"    {band_filename}: {size_mb:.0f} MB [OK]", flush=True)
    return True


# ============================================================
# 获取 Granule 名称
# ============================================================
def get_granule_name(product_id, safe_name):
    token = get_access_token()
    url = f"{ZIPPER_URL}({product_id})/Nodes({safe_name})/Nodes(GRANULE)/Nodes"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return None
    nodes = resp.json().get("result", resp.json().get("value", []))
    if nodes:
        return nodes[0].get("Name", nodes[0].get("Id"))
    return None


# ============================================================
# 处理单月
# ============================================================
def process_month(year, month, product):
    """下载单月最佳影像的 B3 和 B11"""
    pid = product["Id"]
    name = product["Name"]
    safe_name = name  # e.g. S2A_MSIL2A_20240102T031131_...SAFE

    month_dir = os.path.join(OUTPUT_DIR, f"{year}_{month:02d}")
    os.makedirs(month_dir, exist_ok=True)

    # 获取 granule 名称
    granule = get_granule_name(pid, safe_name)
    if not granule:
        print(f"  [错误] 无法获取 Granule 名称")
        return False

    # 从产品名提取瓦片和日期信息来构造波段文件名
    # S2A_MSIL2A_20240102T031131_N0510_R075_T50TMK_20240102T053346.SAFE
    parts = name.replace(".SAFE", "").split("_")
    tile = parts[5]      # T50TMK
    datetime_str = parts[2]  # 20240102T031131

    b3_filename = f"{tile}_{datetime_str}_B03_10m.jp2"
    b11_filename = f"{tile}_{datetime_str}_B11_20m.jp2"

    b3_path = os.path.join(month_dir, b3_filename)
    b11_path = os.path.join(month_dir, b11_filename)

    # 下载 B3 (10m)
    if os.path.exists(b3_path) and os.path.getsize(b3_path) > 1000:
        print(f"    [跳过] {b3_filename} 已存在")
    else:
        if not download_band_file(pid, safe_name, granule, "R10m", b3_filename, b3_path):
            return False

    # 下载 B11 (20m)
    if os.path.exists(b11_path) and os.path.getsize(b11_path) > 1000:
        print(f"    [跳过] {b11_filename} 已存在")
    else:
        if not download_band_file(pid, safe_name, granule, "R20m", b11_filename, b11_path):
            return False

    # 保存元数据
    meta = {"product": name, "cloud_cover": product["_cloud"], "tile": tile, "date": datetime_str,
            "b3": b3_path, "b11": b11_path}
    with open(os.path.join(month_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    return True


# ============================================================
# 主流程
# ============================================================
def main():
    print("=" * 60)
    print(f"Sentinel-2 L2A 波段下载 - 官厅水库 {YEAR}年")
    print(f"下载波段: B3 (10m) + B11 (20m)")
    print(f"云量阈值: ≤{MAX_CLOUD}%")
    print(f"输出目录: {OUTPUT_DIR}")
    print("=" * 60)

    print("\n[认证] 获取 access token...")
    get_access_token()
    print("[认证] OK")

    results = []

    for month in range(5, 11):
        print(f"\n{'─'*50}")
        print(f"  {YEAR}年{month:02d}月")
        print(f"{'─'*50}")

        products = search_monthly(YEAR, month)

        if not products:
            print(f"  [无数据] 无满足云量≤{MAX_CLOUD}%的影像")
            results.append({"month": f"{YEAR}_{month:02d}", "status": "no_data"})
            continue

        best = products[0]
        print(f"  最佳影像: {best['Name']}")
        print(f"  云量: {best['_cloud']}%")

        try:
            ok = process_month(YEAR, month, best)
            results.append({
                "month": f"{YEAR}_{month:02d}",
                "product": best["Name"],
                "cloud_cover": best["_cloud"],
                "status": "ok" if ok else "error"
            })
        except Exception as e:
            print(f"  [错误] {e}")
            results.append({
                "month": f"{YEAR}_{month:02d}",
                "product": best["Name"],
                "status": "error",
                "error": str(e)
            })

        time.sleep(1)

    # 汇总
    print("\n" + "=" * 60)
    print("下载汇总")
    print("=" * 60)
    ok_count = sum(1 for r in results if r["status"] == "ok")
    no_data = sum(1 for r in results if r["status"] == "no_data")
    err_count = sum(1 for r in results if r["status"] == "error")
    print(f"  成功: {ok_count} | 无数据: {no_data} | 失败: {err_count}")

    for r in results:
        icon = "✓" if r["status"] == "ok" else ("–" if r["status"] == "no_data" else "✗")
        cloud = f" cloud={r.get('cloud_cover', '?')}%" if r.get("cloud_cover") else ""
        print(f"  {icon} {r['month']}{cloud}")

    record_path = os.path.join(OUTPUT_DIR, "download_record.json")
    with open(record_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n记录文件: {record_path}")


if __name__ == "__main__":
    main()
