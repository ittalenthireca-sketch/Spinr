import asyncio
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

try:
    from .supabase_client import supabase  # type: ignore
except ImportError:
    from supabase_client import supabase  # type: ignore

from typing import Callable, TypeVar

from loguru import logger

T = TypeVar("T")


async def run_sync(func: Callable[[], T]) -> T:
    """Run a synchronous Supabase call in a thread and retry once on transient
    HTTP/2 connection errors (h2.ConnectionTerminated / GOAWAY) that Supabase
    sends when the stream limit is reached on a long-lived connection."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, func)  # type: ignore
    except Exception as exc:
        exc_name = type(exc).__name__
        exc_str = str(exc)
        if "ConnectionTerminated" in exc_name or "ConnectionTerminated" in exc_str:
            logger.warning(f"Supabase HTTP/2 ConnectionTerminated — retrying once: {exc}")
            await asyncio.sleep(0.25)
            return await loop.run_in_executor(None, func)  # type: ignore
        raise


def _serialize_for_api(data: Any) -> Any:
    """Recursively convert datetime/date objects to ISO format strings."""
    if isinstance(data, dict):
        return {k: _serialize_for_api(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_serialize_for_api(v) for v in data]
    if isinstance(data, (datetime, date)):
        return data.isoformat()
    return data


def _single_row_from_res(res: Any) -> Optional[Dict[str, Any]]:
    if not res:
        return None
    # Handle both dict-based responses and supabase APIResponse objects
    data = None
    if isinstance(res, dict):
        data = res.get("data")
    else:
        # supabase-py returns an APIResponse with .data attribute
        data = getattr(res, "data", None)

    if not data:
        return None

    if isinstance(data, list):
        return data[0] if len(data) > 0 else None
    return data


def _rows_from_res(res: Any) -> List[Dict[str, Any]]:
    if not res:
        return []

    data = None
    if isinstance(res, dict):
        data = res.get("data")
    else:
        data = getattr(res, "data", None)

    return data or []


# ============ Corporate Accounts Functions ============


async def get_all_corporate_accounts(
    skip: int = 0, limit: int = 100, search: Optional[str] = None, is_active: Optional[bool] = None
) -> List[Dict[str, Any]]:
    """
    Get all corporate accounts with optional filtering and pagination.

    Args:
        skip: Number of records to skip
        limit: Maximum number of records to return
        search: Search term for company name, contact name, or email
        is_active: Filter by active status

    Returns:
        List of corporate accounts
    """
    if not supabase:
        return []

    def _fn():
        query = supabase.table("corporate_accounts").select("*").range(skip, skip + limit - 1)

        if search:
            # Escape special PostgREST ilike characters to prevent filter injection
            safe = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            # Strip characters that could break PostgREST filter syntax
            safe = re.sub(r"[,\.\(\)]", "", safe)
            query = query.or_(f"name.ilike.%{safe}%,contact_name.ilike.%{safe}%,contact_email.ilike.%{safe}%")

        if is_active is not None:
            query = query.eq("is_active", is_active)

        query = query.order("created_at", desc=True)
        return _rows_from_res(query.execute())

    return await run_sync(_fn)


async def get_corporate_account_by_id(validated_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a corporate account by ID.

    Args:
        validated_id: Validated corporate account ID

    Returns:
        Corporate account data or None if not found
    """
    if not supabase:
        return None

    def _fn():
        try:
            res = supabase.table("corporate_accounts").select("*").eq("id", validated_id).single().execute()
            return _single_row_from_res(res)
        except Exception as e:
            # If no rows found, Supabase raises an exception
            logger.debug(f"No corporate account found with ID {validated_id}: {e}")
            return None

    return await run_sync(_fn)


async def insert_corporate_account(account_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Insert a new corporate account.

    Args:
        account_data: Corporate account data to insert

    Returns:
        Created corporate account data or None if failed
    """
    if not supabase:
        raise RuntimeError("Supabase client not configured")

    account_data = _serialize_for_api(account_data)

    def _fn():
        res = supabase.table("corporate_accounts").insert(account_data).execute()
        return _single_row_from_res(res)

    return await run_sync(_fn)


async def update_corporate_account(account_id: str, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Update an existing corporate account.

    Args:
        account_id: ID of the account to update
        update_data: Data to update

    Returns:
        Updated corporate account data or None if failed
    """
    if not supabase:
        return None

    update_data = _serialize_for_api(update_data)

    def _fn():
        res = supabase.table("corporate_accounts").update(update_data).eq("id", account_id).execute()
        return _single_row_from_res(res)

    return await run_sync(_fn)


async def delete_corporate_account(account_id: str) -> bool:
    """
    Delete a corporate account.

    Args:
        account_id: ID of the account to delete

    Returns:
        True if successful, False otherwise
    """
    if not supabase:
        return False

    def _fn():
        res = supabase.table("corporate_accounts").delete().eq("id", account_id).execute()
        # If deletion was successful, affected rows will be > 0
        return res.count > 0 if res.count is not None else False

    return await run_sync(_fn)


# ============ User Helpers ============


async def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    if not supabase:
        return None
    return await run_sync(lambda: _single_row_from_res(supabase.table("users").select("*").eq("id", user_id).execute()))


async def get_user_by_phone(phone: str) -> Optional[Dict[str, Any]]:
    if not supabase:
        return None
    return await run_sync(
        lambda: _single_row_from_res(supabase.table("users").select("*").eq("phone", phone).execute())
    )


async def create_user(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not supabase:
        raise RuntimeError("Supabase client not configured")
    payload = _serialize_for_api(payload)
    return await run_sync(lambda: _single_row_from_res(supabase.table("users").insert(payload).execute()))


# ============ Driver Helpers ============


async def get_driver_by_id(driver_id: str) -> Optional[Dict[str, Any]]:
    if not supabase:
        return None
    return await run_sync(
        lambda: _single_row_from_res(supabase.table("drivers").select("*").eq("id", driver_id).execute())
    )


async def find_nearby_drivers(lat: float, lng: float, radius_meters: float) -> List[Dict[str, Any]]:
    """Use PostGIS RPC to find nearby drivers."""
    if not supabase:
        return []

    def _fn():
        res = supabase.rpc("find_nearby_drivers", {"lat": lat, "lng": lng, "radius_meters": radius_meters}).execute()
        return _rows_from_res(res)

    return await run_sync(_fn)


async def update_driver_location(driver_id: str, lat: float, lng: float):
    if not supabase:
        return None

    def _update():
        # The Supabase RPC seems to have a type mismatch (text vs uuid) error.
        # We'll bypass the RPC and update the table directly.
        # Assuming table has 'lat' and 'lng' columns (or 'location' if that works, but Traceback used lat/lng).

        # Note: If 'location' is a PostGIS column, we might need to update it too.
        # But failing RPC prevents any update. Direct update is safer for now.

        data = {"lat": lat, "lng": lng, "updated_at": datetime.utcnow().isoformat()}
        supabase.table("drivers").update(data).eq("id", str(driver_id)).execute()
        return True

    return await run_sync(_update)


async def set_driver_available(driver_id: str, available: bool = True, total_rides_inc: int = 0):
    if not supabase:
        logger.warning("[GO-ONLINE] set_driver_available: supabase client is None!")
        return None

    def _update():
        payload: Dict[str, Any] = {"is_available": available}
        logger.info(
            f"[GO-ONLINE] set_driver_available CALLED driver_id={driver_id} "
            f"available={available} total_rides_inc={total_rides_inc} "
            f"payload={payload} (NOTE: only writes is_available, drops any "
            f"other fields the caller may have passed)"
        )
        if total_rides_inc == 0:
            res = supabase.table("drivers").update(payload).eq("id", driver_id).execute()
            logger.info(f"[GO-ONLINE] set_driver_available executed, res.data={getattr(res, 'data', None)}")
            return _single_row_from_res(res)

        # If increment needed, read then write (simulated atomic)
        # Ideally this should be an RPC or a better query if Supabase supported $inc
        cur = supabase.table("drivers").select("total_rides").eq("id", driver_id).execute()
        cur_data = _rows_from_res(cur)
        cur_val = cur_data[0].get("total_rides", 0) if cur_data else 0

        payload["total_rides"] = cur_val + total_rides_inc
        res = supabase.table("drivers").update(payload).eq("id", driver_id).execute()
        return _single_row_from_res(res)

    return await run_sync(_update)


async def claim_driver_atomic(driver_id: str) -> bool:
    """Atomically set is_available = false for driver if currently available."""
    if not supabase:
        return False

    def _claim():
        res = (
            supabase.table("drivers")
            .update({"is_available": False})
            .eq("id", driver_id)
            .eq("is_available", True)
            .execute()
        )
        data = _rows_from_res(res)
        return len(data) > 0

    return await run_sync(_claim)


async def claim_ride_atomic(ride_id: str, driver_id: str) -> bool:
    """Atomically claim a ride offer for `driver_id`.

    Issues a single conditional UPDATE that sets
    ``status='driver_accepted'`` and ``driver_id=<driver>`` only if the
    ride is (1) identified by `ride_id`, (2) in an open, claimable state
    (`searching` or `driver_assigned`), and (3) either unassigned or
    already pre-assigned to THIS driver. Supabase's PostgREST layer
    evaluates all three filters atomically in one SQL statement, so two
    drivers racing to accept the same offer cannot both succeed — the
    loser's UPDATE matches zero rows and this function returns False.

    Returns:
        True  — we successfully claimed the ride and the driver-app can
                proceed with the ride flow.
        False — the ride was gone or already accepted by another driver;
                the caller should surface a "ride already taken" UX.
    """
    if not supabase:
        return False

    now_iso = datetime.utcnow().isoformat()

    def _claim():
        res = (
            supabase.table("rides")
            .update(
                {
                    "status": "driver_accepted",
                    "driver_id": driver_id,
                    "driver_accepted_at": now_iso,
                    "updated_at": now_iso,
                }
            )
            .eq("id", ride_id)
            # Status must be open/claimable. Any status past `driver_accepted`
            # (arrived / in_progress / completed / cancelled) is terminal for
            # the accept flow.
            .in_("status", ["searching", "driver_assigned"])
            # Ride must be either unassigned or already pre-assigned to this
            # driver. PostgREST's `.or_()` accepts a comma-separated filter
            # list; `is.null` maps to `IS NULL` in SQL.
            .or_(f"driver_id.is.null,driver_id.eq.{driver_id}")
            .execute()
        )
        data = _rows_from_res(res)
        return len(data) > 0

    return await run_sync(_claim)


# ============ Ride Helpers ============


async def get_ride(ride_id: str) -> Optional[Dict[str, Any]]:
    if not supabase:
        return None
    return await run_sync(lambda: _single_row_from_res(supabase.table("rides").select("*").eq("id", ride_id).execute()))


async def insert_ride(payload: Dict[str, Any]):
    if not supabase:
        raise RuntimeError("Supabase client not configured")
    payload = _serialize_for_api(payload)
    return await run_sync(lambda: _single_row_from_res(supabase.table("rides").insert(payload).execute()))


async def update_ride(ride_id: str, updates: Dict[str, Any]):
    if not supabase:
        return None
    # Strip MongoDB-style $set wrapper if present
    updates = updates.get("$set", updates)
    updates = _serialize_for_api(updates)
    return await run_sync(
        lambda: _single_row_from_res(supabase.table("rides").update(updates).eq("id", ride_id).execute())
    )


async def get_rides_for_user(rider_id: str, limit: int = 100):
    if not supabase:
        return []
    return await run_sync(
        lambda: _rows_from_res(
            supabase.table("rides")
            .select("*")
            .eq("rider_id", rider_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
    )


async def get_rides_for_driver(driver_id: str, statuses: Optional[List[str]] = None, limit: int = 100):
    if not supabase:
        return []

    def _fn():
        q = supabase.table("rides").select("*").eq("driver_id", driver_id)
        if statuses:
            status_filters = ",".join([f"status.eq.{s}" for s in statuses])
            q = q.or_(status_filters)
        q = q.order("created_at", desc=True).limit(limit)
        return _rows_from_res(q.execute())

    return await run_sync(_fn)


# ============ OTP Helpers ============


async def insert_otp_record(payload: Dict[str, Any]):
    if not supabase:
        raise RuntimeError("Supabase client not configured")
    payload = _serialize_for_api(payload)
    return await run_sync(lambda: _single_row_from_res(supabase.table("otp_records").insert(payload).execute()))


async def get_otp_record(phone: str, code: str) -> Optional[Dict[str, Any]]:
    if not supabase:
        return None
    return await run_sync(
        lambda: _single_row_from_res(
            supabase.table("otp_records")
            .select("*")
            .eq("phone", phone)
            .eq("code", code)
            .eq("verified", False)
            .execute()
        )
    )


async def verify_otp_record(record_id: str):
    if not supabase:
        return None
    return await run_sync(
        lambda: _single_row_from_res(
            supabase.table("otp_records").update({"verified": True}).eq("id", record_id).execute()
        )
    )


async def delete_otp_record(record_id: str):
    if not supabase:
        return None
    return await run_sync(
        lambda: _single_row_from_res(supabase.table("otp_records").delete().eq("id", record_id).execute())
    )


# ============ Query Helpers ============


def _apply_filters(q, filters: Optional[Dict[str, Any]]):
    if not filters:
        return q
    for k, v in filters.items():
        if isinstance(v, dict):
            if "$in" in v and isinstance(v["$in"], (list, tuple)):
                q = q.in_(k, list(v["$in"]))
            elif "$gt" in v:
                q = q.gt(k, v["$gt"])
            elif "$gte" in v:
                q = q.gte(k, v["$gte"])
            elif "$lt" in v:
                q = q.lt(k, v["$lt"])
            elif "$lte" in v:
                q = q.lte(k, v["$lte"])
            elif "$ne" in v:
                q = q.neq(k, v["$ne"])
            # Add more query operators as needed
        else:
            q = q.eq(k, v)
    return q


async def get_rows(
    table: str,
    filters: Optional[Dict[str, Any]] = None,
    order: Optional[str] = None,
    desc: bool = False,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
):
    if not supabase:
        return []

    def _fn():
        q = supabase.table(table).select("*")
        q = _apply_filters(q, filters)
        if order:
            q = q.order(order, desc=desc)
        if limit is not None and offset is not None:
            # Supabase .range is 0-based inclusive: range(offset, offset+limit-1)
            q = q.range(offset, offset + limit - 1)
        elif limit:
            q = q.limit(limit)
        elif offset is not None:
            q = q.offset(offset)
        return _rows_from_res(q.execute())

    return await run_sync(_fn)


async def count_documents(table: str, filters: Optional[Dict[str, Any]] = None) -> int:
    if not supabase:
        return 0

    def _fn():
        # count="exact" makes PostgREST include the total count in Content-Range.
        # We limit to 1 row so we don't fetch the full dataset; res.count still
        # reflects the total rows matching the filter (not the page size).
        # Note: head=True is NOT a valid parameter for select() in postgrest-py
        # 2.x — using it would raise TypeError and cause a 500 on every call.
        q = supabase.table(table).select("id", count="exact")
        q = _apply_filters(q, filters)
        q = q.limit(1)
        res = q.execute()
        if hasattr(res, "count") and res.count is not None:
            return int(res.count)
        return 0

    return await run_sync(_fn)


async def insert_one(table: str, doc: Dict[str, Any]):
    if not supabase:
        return None
    doc = _serialize_for_api(doc)
    return await run_sync(lambda: _single_row_from_res(supabase.table(table).insert(doc).execute()))


async def insert_many(table: str, docs: List[Dict[str, Any]]):
    """Bulk insert using Supabase's native batch insert (single round-trip)."""
    if not supabase or not docs:
        return []
    serialized = [_serialize_for_api(d) for d in docs]
    return await run_sync(lambda: _rows_from_res(supabase.table(table).insert(serialized).execute()))


async def update_one(table: str, filters: Dict[str, Any], update: Dict[str, Any], upsert: bool = False):
    if not supabase:
        if table == "drivers":
            logger.warning("[GO-ONLINE] db_supabase.update_one: supabase client is None!")
        return None

    def _fn():
        update_data = update.get("$set", update)
        update_data = _serialize_for_api(update_data)

        if table == "drivers":
            logger.info(
                f"[GO-ONLINE] db_supabase.update_one about to execute: "
                f"table={table} filters={filters} payload={update_data} upsert={upsert}"
            )

        if upsert:
            # Upsert requires merging filters and update data
            payload = {**filters, **update_data}
            res = supabase.table(table).upsert(payload).execute()
        else:
            q = supabase.table(table).update(update_data)
            q = _apply_filters(q, filters)
            res = q.execute()

        if table == "drivers":
            raw_data = None
            try:
                raw_data = getattr(res, "data", None) if res else None
            except Exception:
                raw_data = "<error reading res.data>"
            logger.info(
                f"[GO-ONLINE] db_supabase.update_one executed: "
                f"res_type={type(res).__name__ if res else 'None'} "
                f"res_data={raw_data}"
            )

        return _single_row_from_res(res)

    return await run_sync(_fn)


async def delete_many(table: str, filters: Dict[str, Any]):
    if not supabase:
        return None

    def _fn():
        q = supabase.table(table).delete()
        q = _apply_filters(q, filters)
        res = q.execute()
        return _rows_from_res(res)

    return await run_sync(_fn)


async def delete_one(table: str, filters: Dict[str, Any]):
    # Note: Supabase delete is always "delete matching rows".
    # To delete strictly one, we'd need to limit, but delete doesn't support limit easily in basic client.
    # We'll just use delete_many logic but maybe warn if we wanted only one.
    return await delete_many(table, filters)


async def rpc(func_name: str, params: Dict[str, Any]):
    if not supabase:
        return None

    def _fn():
        res = supabase.rpc(func_name, params).execute()
        return _rows_from_res(res)

    return await run_sync(_fn)


# ============ Rides Admin Dashboard – New Helpers ============


async def get_ride_count_by_date_range(start_iso: str, end_iso: str) -> int:
    """Count rides created within a date range using Supabase SDK."""
    if not supabase:
        return 0

    def _fn():
        res = (
            supabase.table("rides")
            .select("id", count="exact")
            .limit(1)
            .gte("created_at", start_iso)
            .lt("created_at", end_iso)
            .execute()
        )
        if hasattr(res, "count") and res.count is not None:
            return int(res.count)
        return 0

    return await run_sync(_fn)


async def get_ride_details_enriched(ride_id: str) -> Optional[Dict[str, Any]]:
    """Get a ride with enriched rider/driver details, flags, complaints, lost items."""
    if not supabase:
        return None

    def _get_ride():
        return _single_row_from_res(supabase.table("rides").select("*").eq("id", ride_id).execute())

    ride = await run_sync(_get_ride)
    if not ride:
        return None

    # Fetch rider details
    rider_id = ride.get("rider_id")
    if rider_id:
        rider = await run_sync(
            lambda rid=rider_id: _single_row_from_res(
                supabase.table("users")
                .select("first_name,last_name,phone,email,profile_image,status,created_at")
                .eq("id", rid)
                .execute()
            )
        )
        if rider:
            ride["rider_name"] = f"{rider.get('first_name', '')} {rider.get('last_name', '')}".strip() or rider_id[:12]
            ride["rider_phone"] = rider.get("phone", "")
            ride["rider_email"] = rider.get("email", "")
            ride["rider_profile_image"] = rider.get("profile_image", "")
            ride["rider_status"] = rider.get("status", "active")
            ride["rider_joined"] = rider.get("created_at", "")

        # Rider's service area (region) from most recent ride
        rider_area = await run_sync(
            lambda rid=rider_id: _single_row_from_res(
                supabase.table("rides")
                .select("service_area_id")
                .eq("rider_id", rid)
                .neq("service_area_id", "null")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
        )
        rider_area_id = rider_area.get("service_area_id") if rider_area else None
        if rider_area_id:
            area = await run_sync(
                lambda aid=rider_area_id: _single_row_from_res(
                    supabase.table("service_areas").select("name,city").eq("id", aid).execute()
                )
            )
            ride["rider_region"] = area.get("name", "") if area else ""
            ride["rider_city"] = area.get("city", "") if area else ""
        else:
            ride["rider_region"] = ""
            ride["rider_city"] = ""

        # Rider's total past rides count
        rider_count_res = await run_sync(
            lambda rid=rider_id: (
                supabase.table("rides").select("id", count="exact").limit(1).eq("rider_id", rid).execute()
            )
        )
        ride["rider_total_rides"] = (
            int(rider_count_res.count) if hasattr(rider_count_res, "count") and rider_count_res.count is not None else 0
        )

    # Fetch driver details
    driver_id = ride.get("driver_id")
    if driver_id:
        driver = await run_sync(
            lambda did=driver_id: _single_row_from_res(
                supabase.table("drivers")
                .select(
                    "name,phone,vehicle_make,vehicle_model,vehicle_color,vehicle_year,vehicle_vin,license_plate,rating,status,photo_url,vehicle_type_id,total_rides,service_area_id"
                )
                .eq("id", did)
                .execute()
            )
        )
        if driver:
            ride["driver_name"] = driver.get("name", driver_id[:12])
            ride["driver_phone"] = driver.get("phone", "")
            ride["driver_vehicle_make"] = driver.get("vehicle_make", "")
            ride["driver_vehicle_model"] = driver.get("vehicle_model", "")
            ride["driver_vehicle_color"] = driver.get("vehicle_color", "")
            ride["driver_vehicle_year"] = driver.get("vehicle_year")
            ride["driver_vehicle_vin"] = driver.get("vehicle_vin", "")
            ride["driver_license_plate"] = driver.get("license_plate", "")
            ride["driver_rating"] = driver.get("rating", 0)
            ride["driver_status"] = driver.get("status", "active")
            ride["driver_photo_url"] = driver.get("photo_url", "")

            # Driver region/service area
            driver_area_id = driver.get("service_area_id")
            if driver_area_id:
                d_area = await run_sync(
                    lambda aid=driver_area_id: _single_row_from_res(
                        supabase.table("service_areas").select("name,city").eq("id", aid).execute()
                    )
                )
                ride["driver_region"] = d_area.get("name", "") if d_area else ""
                ride["driver_city"] = d_area.get("city", "") if d_area else ""
            else:
                ride["driver_region"] = ""
                ride["driver_city"] = ""
            ride["driver_vehicle"] = f"{driver.get('vehicle_make', '')} {driver.get('vehicle_model', '')}".strip()
            ride["driver_total_rides"] = driver.get("total_rides", 0)

            # Compute acceptance rate: completed / (completed + cancelled as driver)
            vtype_id = driver.get("vehicle_type_id")
            if vtype_id:
                vtype = await run_sync(
                    lambda vid=vtype_id: _single_row_from_res(
                        supabase.table("vehicle_types").select("name,description,capacity").eq("id", vid).execute()
                    )
                )
                if vtype:
                    ride["driver_vehicle_type_name"] = vtype.get("name", "")
                    ride["driver_vehicle_capacity"] = vtype.get("capacity", 0)

            # Acceptance rate: total rides assigned to driver vs cancelled by driver
            driver_completed_res = await run_sync(
                lambda did=driver_id: (
                    supabase.table("rides")
                    .select("id", count="exact")
                    .limit(1)
                    .eq("driver_id", did)
                    .eq("status", "completed")
                    .execute()
                )
            )
            completed = (
                int(driver_completed_res.count)
                if hasattr(driver_completed_res, "count") and driver_completed_res.count is not None
                else 0
            )
            driver_total_assigned_res = await run_sync(
                lambda did=driver_id: (
                    supabase.table("rides").select("id", count="exact").limit(1).eq("driver_id", did).execute()
                )
            )
            total_assigned = (
                int(driver_total_assigned_res.count)
                if hasattr(driver_total_assigned_res, "count") and driver_total_assigned_res.count is not None
                else 0
            )
            ride["driver_acceptance_rate"] = round((completed / total_assigned * 100), 1) if total_assigned > 0 else 0
            ride["driver_completed_rides"] = completed

    # Fetch flags for both rider and driver
    flags = []
    if rider_id:
        rider_flags = await run_sync(
            lambda rid=rider_id: _rows_from_res(
                supabase.table("flags")
                .select("*")
                .eq("target_type", "rider")
                .eq("target_id", rid)
                .eq("is_active", True)
                .order("created_at", desc=True)
                .execute()
            )
        )
        flags.extend([{**f, "_party": "rider"} for f in rider_flags])
    if driver_id:
        driver_flags = await run_sync(
            lambda did=driver_id: _rows_from_res(
                supabase.table("flags")
                .select("*")
                .eq("target_type", "driver")
                .eq("target_id", did)
                .eq("is_active", True)
                .order("created_at", desc=True)
                .execute()
            )
        )
        flags.extend([{**f, "_party": "driver"} for f in driver_flags])
    ride["flags"] = flags
    ride["rider_flag_count"] = sum(1 for f in flags if f.get("_party") == "rider")
    ride["driver_flag_count"] = sum(1 for f in flags if f.get("_party") == "driver")

    # Fetch complaints for this ride
    ride["complaints"] = await run_sync(
        lambda: _rows_from_res(
            supabase.table("complaints").select("*").eq("ride_id", ride_id).order("created_at", desc=True).execute()
        )
    )

    # Fetch lost and found items for this ride
    ride["lost_and_found"] = await run_sync(
        lambda: _rows_from_res(
            supabase.table("lost_and_found").select("*").eq("ride_id", ride_id).order("created_at", desc=True).execute()
        )
    )

    # Fetch location trail for this ride
    ride["location_trail"] = await run_sync(
        lambda: _rows_from_res(
            supabase.table("driver_location_history")
            .select("lat,lng,speed,heading,tracking_phase,timestamp")
            .eq("ride_id", ride_id)
            .order("timestamp")
            .limit(5000)
            .execute()
        )
    )

    return ride


async def create_flag(flag_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a flag and check if auto-ban threshold (3) is reached."""
    if not supabase:
        raise RuntimeError("Supabase client not configured")

    flag_data = _serialize_for_api(flag_data)

    # Insert flag
    flag = await run_sync(lambda: _single_row_from_res(supabase.table("flags").insert(flag_data).execute()))

    # Count active flags for this target
    target_type = flag_data["target_type"]
    target_id = flag_data["target_id"]

    count_res = await run_sync(
        lambda: (
            supabase.table("flags")
            .select("id", count="exact")
            .limit(1)
            .eq("target_type", target_type)
            .eq("target_id", target_id)
            .eq("is_active", True)
            .execute()
        )
    )
    active_count = int(count_res.count) if hasattr(count_res, "count") and count_res.count is not None else 0

    auto_banned = False
    if active_count >= 3:
        ban_table = "users" if target_type == "rider" else "drivers"
        await run_sync(lambda: supabase.table(ban_table).update({"status": "banned"}).eq("id", target_id).execute())
        auto_banned = True

    return {"flag": flag, "active_flag_count": active_count, "auto_banned": auto_banned}


async def create_complaint(complaint_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Insert a complaint record."""
    if not supabase:
        raise RuntimeError("Supabase client not configured")
    complaint_data = _serialize_for_api(complaint_data)
    return await run_sync(lambda: _single_row_from_res(supabase.table("complaints").insert(complaint_data).execute()))


async def resolve_complaint(complaint_id: str, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Resolve or dismiss a complaint."""
    if not supabase:
        return None
    update_data = _serialize_for_api(update_data)
    return await run_sync(
        lambda: _single_row_from_res(supabase.table("complaints").update(update_data).eq("id", complaint_id).execute())
    )


async def create_lost_and_found(item_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Insert a lost and found report."""
    if not supabase:
        raise RuntimeError("Supabase client not configured")
    item_data = _serialize_for_api(item_data)
    return await run_sync(lambda: _single_row_from_res(supabase.table("lost_and_found").insert(item_data).execute()))


async def update_lost_and_found(item_id: str, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update a lost and found item status."""
    if not supabase:
        return None
    update_data = _serialize_for_api(update_data)
    return await run_sync(
        lambda: _single_row_from_res(supabase.table("lost_and_found").update(update_data).eq("id", item_id).execute())
    )


async def get_ride_location_trail(ride_id: str) -> List[Dict[str, Any]]:
    """Get driver location trail for a specific ride."""
    if not supabase:
        return []
    return await run_sync(
        lambda: _rows_from_res(
            supabase.table("driver_location_history")
            .select("lat,lng,speed,heading,tracking_phase,timestamp")
            .eq("ride_id", ride_id)
            .order("timestamp")
            .limit(5000)
            .execute()
        )
    )


async def get_live_ride_data(ride_id: str) -> Optional[Dict[str, Any]]:
    """Get live ride data including current driver location."""
    if not supabase:
        return None

    ride = await run_sync(lambda: _single_row_from_res(supabase.table("rides").select("*").eq("id", ride_id).execute()))
    if not ride:
        return None

    driver_id = ride.get("driver_id")
    if driver_id:
        driver = await run_sync(
            lambda did=driver_id: _single_row_from_res(
                supabase.table("drivers")
                .select("name,phone,lat,lng,vehicle_make,vehicle_model,vehicle_color,license_plate,rating,photo_url")
                .eq("id", did)
                .execute()
            )
        )
        if driver:
            ride["driver_current_lat"] = driver.get("lat", 0)
            ride["driver_current_lng"] = driver.get("lng", 0)
            ride["driver_name"] = driver.get("name", "")
            ride["driver_phone"] = driver.get("phone", "")
            ride["driver_vehicle"] = f"{driver.get('vehicle_make', '')} {driver.get('vehicle_model', '')}".strip()
            ride["driver_license_plate"] = driver.get("license_plate", "")
            ride["driver_rating"] = driver.get("rating", 0)
            ride["driver_photo_url"] = driver.get("photo_url", "")

    rider_id = ride.get("rider_id")
    if rider_id:
        rider = await run_sync(
            lambda rid=rider_id: _single_row_from_res(
                supabase.table("users").select("first_name,last_name,phone").eq("id", rid).execute()
            )
        )
        if rider:
            ride["rider_name"] = f"{rider.get('first_name', '')} {rider.get('last_name', '')}".strip()
            ride["rider_phone"] = rider.get("phone", "")

    return ride


async def get_user_status(user_id: str) -> Optional[str]:
    """Get user account status (active/suspended/banned)."""
    if not supabase:
        return None
    user = await run_sync(
        lambda: _single_row_from_res(supabase.table("users").select("status").eq("id", user_id).execute())
    )
    return user.get("status", "active") if user else None


async def get_driver_status_by_user(user_id: str) -> Optional[str]:
    """Get driver account status by user_id (active/suspended/banned)."""
    if not supabase:
        return None
    driver = await run_sync(
        lambda: _single_row_from_res(supabase.table("drivers").select("status").eq("user_id", user_id).execute())
    )
    return driver.get("status", "active") if driver else None


async def get_flags_for_target(target_type: str, target_id: str) -> List[Dict[str, Any]]:
    """Get all active flags for a rider or driver."""
    if not supabase:
        return []
    return await run_sync(
        lambda: _rows_from_res(
            supabase.table("flags")
            .select("*")
            .eq("target_type", target_type)
            .eq("target_id", target_id)
            .eq("is_active", True)
            .order("created_at", desc=True)
            .execute()
        )
    )


# ── Stripe webhook idempotency ────────────────────────────────────────
# See migration 22_stripe_events.sql. These helpers back
# routes/webhooks.py's dedup path: Stripe retries every event until we
# return 2xx within 20s, so we MUST treat a replay of the same event.id
# as a no-op — otherwise we double-mark rides paid, double-credit
# wallets, and double-activate subscriptions.

# PostgreSQL unique_violation SQLSTATE — raised as part of the error
# string by postgrest-py when an INSERT conflicts with the PK.
_PG_UNIQUE_VIOLATION = "23505"


async def claim_stripe_event(event_id: str, event_type: str, payload: Dict[str, Any]) -> bool:
    """Atomically claim a Stripe webhook event for processing.

    Returns True if this call inserted the event row (caller should
    proceed to process it). Returns False if the event_id is already
    present (a retry — caller should return 200 without doing work).

    Raises if Supabase is unreachable or the error is not a unique
    violation — in that case the caller should return 5xx so Stripe
    retries later.
    """
    if not supabase:
        raise RuntimeError("Supabase client not configured — cannot persist stripe event")

    serialized_payload = _serialize_for_api(payload)

    def _fn() -> bool:
        try:
            supabase.table("stripe_events").insert(
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "payload": serialized_payload,
                }
            ).execute()
            return True
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            if _PG_UNIQUE_VIOLATION in msg or "duplicate key" in msg or "already exists" in msg:
                logger.info(f"Stripe event {event_id} already claimed — treating as duplicate")
                return False
            raise

    return await run_sync(_fn)


async def mark_stripe_event_processed(event_id: str) -> None:
    """Stamp processed_at=now() on a previously claimed stripe event row.

    Called after the handler has finished the business-logic work for
    an event. Failure here is non-fatal — the reconciliation job can
    still distinguish processed vs. stuck events by the presence of
    the updated_at stamp, and Stripe will not retry since we returned
    2xx. Log and swallow.
    """
    if not supabase:
        return

    def _fn():
        supabase.table("stripe_events").update({"processed_at": datetime.now(timezone.utc).isoformat()}).eq(
            "event_id", event_id
        ).execute()

    try:
        await run_sync(_fn)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to stamp processed_at on stripe event {event_id}: {e}")


async def fetch_unprocessed_stripe_events(limit: int = 10) -> list[Dict[str, Any]]:
    """Return up to ``limit`` Stripe events ready to be (re-)dispatched.

    "Ready" = ``processed_at IS NULL`` AND (``next_attempt_at IS NULL``
    OR ``next_attempt_at <= now()``). The ordering is
    ``received_at ASC`` so older events drain first — this preserves the
    logical "accepted a payment then failed the follow-up" ordering
    callers may depend on.

    Fields returned: event_id, event_type, payload, attempt_count.

    Used by ``utils.stripe_worker`` on the worker process. A NULL return
    is the steady state when the queue is empty.
    """
    if not supabase:
        return []

    now_iso = datetime.now(timezone.utc).isoformat()

    def _fn() -> list[Dict[str, Any]]:
        # Two separate queries OR'd in the client: PostgREST has no first-
        # class "col IS NULL OR col <= X" predicate, so we union the two
        # partitions explicitly.  Bounded by ``limit`` on each side to
        # cap total fan-in at 2*limit in the worst case; the worker
        # further slices down after sort.
        never_tried = (
            supabase.table("stripe_events")
            .select("event_id,event_type,payload,attempt_count,received_at")
            .is_("processed_at", "null")
            .is_("next_attempt_at", "null")
            .order("received_at", desc=False)
            .limit(limit)
            .execute()
        )
        due_retry = (
            supabase.table("stripe_events")
            .select("event_id,event_type,payload,attempt_count,received_at")
            .is_("processed_at", "null")
            .lte("next_attempt_at", now_iso)
            .order("received_at", desc=False)
            .limit(limit)
            .execute()
        )
        rows = list(never_tried.data or []) + list(due_retry.data or [])
        # Dedup in case a row races between the two queries.
        seen: set[str] = set()
        deduped: list[Dict[str, Any]] = []
        for r in rows:
            eid = r.get("event_id")
            if eid and eid not in seen:
                seen.add(eid)
                deduped.append(r)
        deduped.sort(key=lambda r: r.get("received_at") or "")
        return deduped[:limit]

    try:
        return await run_sync(_fn)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"fetch_unprocessed_stripe_events failed: {e}")
        return []


async def mark_stripe_event_failed(event_id: str, error: str, attempt_count: int) -> None:
    """Record a dispatch failure and schedule the next retry.

    Exponential backoff: 30s, 1m, 2m, 4m, 8m, 16m, 32m, capped at 1h.
    After ~10 attempts, ``next_attempt_at`` stays capped — operators
    should inspect the row and either fix the root cause or manually
    stamp ``processed_at`` to drop it off the queue.
    """
    if not supabase:
        return

    # Cap the backoff at 60 minutes so stuck events don't fall into a
    # week-long retry hole — surface them in the next hour and operators
    # can intervene if needed.
    backoff_seconds = min(30 * (2 ** max(0, attempt_count)), 3600)
    next_attempt = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)

    def _fn():
        supabase.table("stripe_events").update(
            {
                "attempt_count": attempt_count + 1,
                "last_error": (error or "")[:2000],  # hard cap; avoid OOM on jumbo tracebacks
                "next_attempt_at": next_attempt.isoformat(),
            }
        ).eq("event_id", event_id).execute()

    try:
        await run_sync(_fn)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to record stripe event failure for {event_id}: {e}")


# ────────────────────────────────────────────────────────────────────────
# Background task heartbeats (Phase 1.6 / audit T15)
#
# Every background loop in the worker process calls
# ``record_bg_task_heartbeat`` at the end of each iteration, success or
# failure. ``/health/deep`` reads ``fetch_bg_task_heartbeats`` and
# returns 503 if any row's ``last_run_at`` is older than
# ``2 * expected_interval_seconds`` — catching the "worker alive but
# a single loop wedged" failure mode that API-side DB probes miss.
#
# The helpers fail soft: if Supabase isn't configured, or a write
# fails, we log and move on — a heartbeat write must never take a
# loop down. The readiness probe treats "no heartbeat rows at all"
# as healthy (the table might just be empty at fresh boot).
# ────────────────────────────────────────────────────────────────────────


async def record_bg_task_heartbeat(
    task_name: str,
    expected_interval_seconds: int,
    status: str = "ok",
    error: str | None = None,
) -> None:
    """Upsert a heartbeat for ``task_name``.

    Called at the end of every background loop iteration. Never raises
    — a failed heartbeat must not take the loop down (we'd rather the
    loop keep running and the health check flag it stale than have the
    whole worker crash because the heartbeat table is temporarily
    unreachable).
    """
    if not supabase:
        return

    if status not in ("ok", "error"):
        status = "error"

    now_iso = datetime.now(timezone.utc).isoformat()
    row = {
        "task_name": task_name,
        "last_run_at": now_iso,
        "last_status": status,
        "last_error": (error or "")[:2000] if error else None,
        "expected_interval_seconds": int(expected_interval_seconds),
        "updated_at": now_iso,
    }

    def _fn():
        # on_conflict is required because task_name is the PK — without
        # it PostgREST treats the row as a plain insert and 409s on the
        # second heartbeat.
        supabase.table("bg_task_heartbeat").upsert(
            row, on_conflict="task_name"
        ).execute()

    try:
        await run_sync(_fn)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to record bg_task_heartbeat for {task_name}: {e}")


async def fetch_bg_task_heartbeats() -> list[Dict[str, Any]]:
    """Return every heartbeat row.

    Used by ``/health/deep`` — low cardinality (one row per background
    task, maybe ~10 total) so we don't paginate. Returns ``[]`` on any
    failure so the health endpoint can differentiate "no rows yet" vs
    "DB unreachable" (the DB probe above will have already flagged the
    DB unreachable case).
    """
    if not supabase:
        return []

    def _fn():
        return supabase.table("bg_task_heartbeat").select(
            "task_name,last_run_at,last_status,last_error,expected_interval_seconds"
        ).execute()

    try:
        resp = await run_sync(_fn)
        return list(resp.data or [])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"fetch_bg_task_heartbeats failed: {e}")
        return []


# ────────────────────────────────────────────────────────────────────────
# Metrics helpers (Phase 2.3c / audit T3)
#
# Cheap aggregate queries feeding the Prometheus refresh loop in
# ``utils.metrics.metrics_refresh_loop``. Pulled into db_supabase
# instead of inlining into metrics.py so the SQL stays next to the
# other supabase access helpers and the metrics module stays a pure
# instrumentation surface.
#
# All helpers fail soft — a failed metric read must never bubble up
# because the refresh loop is shared infra.
# ────────────────────────────────────────────────────────────────────────


async def count_unprocessed_stripe_events() -> int:
    """Return the number of rows in ``stripe_events`` with ``processed_at IS NULL``.

    Drives the ``spinr_stripe_queue_depth`` gauge. The queue is the
    async buffer between Stripe's webhook POST and our business-logic
    dispatcher; watching its depth is the single best signal for
    "we're falling behind on payments" and is the basis for the SLO
    alert in Phase 2.4.
    """
    if not supabase:
        return 0

    def _fn():
        return (
            supabase.table("stripe_events")
            .select("event_id", count="exact")
            .is_("processed_at", "null")
            .limit(1)
            .execute()
        )

    try:
        resp = await run_sync(_fn)
        return int(resp.count or 0)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"count_unprocessed_stripe_events failed: {e}")
        return 0


# Ride statuses we consider "active" for the active_rides gauge. Terminal
# statuses (completed, cancelled, rejected) are deliberately excluded so
# the gauge shows the dispatch-pipeline funnel rather than unbounded
# historical counts.
_ACTIVE_RIDE_STATUSES: tuple[str, ...] = (
    "searching",
    "driver_assigned",
    "driver_accepted",
    "driver_arrived",
    "in_progress",
    "pending_payment",
)


async def count_active_rides_by_status() -> Dict[str, int]:
    """Return a ``{status: count}`` map for rides in non-terminal states.

    Drives the ``spinr_active_rides`` gauge. One query per status is
    simpler than a single GROUP BY (PostgREST doesn't natively support
    GROUP BY) and keeps the per-query plan trivially indexed on
    ``status``. Total fan-out: ~6 queries every metrics refresh
    cycle, which at the 30s default cadence is negligible.
    """
    if not supabase:
        return {}

    out: Dict[str, int] = {}
    for status in _ACTIVE_RIDE_STATUSES:

        def _fn(_status: str = status):
            return (
                supabase.table("rides")
                .select("id", count="exact")
                .eq("status", _status)
                .limit(1)
                .execute()
            )

        try:
            resp = await run_sync(_fn)
            out[status] = int(resp.count or 0)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"count_active_rides_by_status({status}) failed: {e}")
            out[status] = 0
    return out


# ── Ride request idempotency ──────────────────────────────────────────
# Backed by alembic 0007_ride_idempotency. Mirrors the
# claim_stripe_event pattern: an insert-or-reject atomic "claim" step
# followed by a separate "record the response" step once the ride is
# successfully created. The lookup is scoped by (key, rider_id) so one
# rider's collision can never expose another rider's ride snapshot.

async def claim_ride_idempotency_key(
    key: str, rider_id: str
) -> tuple[bool, Optional[Dict[str, Any]]]:
    """Atomically claim an idempotency key for this rider.

    Returns:
        (is_new, cached_response)
          * (True, None)  — we inserted a fresh claim row; caller should
                            proceed to create the ride and then call
                            ``record_ride_idempotency_response``.
          * (False, dict) — this key was seen before and the prior
                            response snapshot is cached; caller should
                            return it verbatim as a 200.
          * (False, None) — this key was seen before but the prior
                            request hasn't finished yet (still in
                            flight). Caller should return 409 so the
                            client can retry after a short delay.
    """
    if not supabase:
        # Without Supabase we can't dedupe; fall back to "fresh" and
        # rely on the client not retrying against a no-op backend.
        return (True, None)

    def _insert() -> tuple[bool, Optional[Dict[str, Any]]]:
        try:
            supabase.table("ride_idempotency_keys").insert(
                {"key": key, "rider_id": rider_id}
            ).execute()
            return (True, None)
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            if _PG_UNIQUE_VIOLATION not in msg and "duplicate" not in msg:
                raise
            # Existing row: look it up and return the cached response.
            resp = (
                supabase.table("ride_idempotency_keys")
                .select("response")
                .eq("key", key)
                .eq("rider_id", rider_id)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            if not rows:
                return (False, None)
            cached = rows[0].get("response")
            return (False, cached)

    return await run_sync(_insert)


async def record_ride_idempotency_response(
    key: str, rider_id: str, ride_id: str, response: Dict[str, Any]
) -> None:
    """Stamp the ride_id + response snapshot onto a previously-claimed key.

    Best-effort: a write failure here is non-fatal. Worst case a client
    retry with the same key returns a 409 (in-flight) instead of the
    cached response, and the retry will land as a duplicate ride — which
    is the exact failure mode this table exists to prevent, but would
    require both a Supabase write outage AND a client retry inside the
    same ~seconds window. Log loudly so we can spot it.
    """
    if not supabase:
        return

    snapshot = _serialize_for_api(response)

    def _fn():
        supabase.table("ride_idempotency_keys").update(
            {"ride_id": ride_id, "response": snapshot}
        ).eq("key", key).eq("rider_id", rider_id).execute()

    try:
        await run_sync(_fn)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"Failed to record idempotency response for key={key[:8]}…: {e}"
        )


async def delete_expired_ride_idempotency_keys(older_than_hours: int = 24) -> int:
    """Delete idempotency-key rows older than ``older_than_hours``.

    Called by the nightly retention sweep. Returns the count deleted.
    The rows are harmless to keep but grow without bound if we never
    prune them, and they hold no data of ongoing value after a day.
    """
    if not supabase:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)

    def _fn():
        return (
            supabase.table("ride_idempotency_keys")
            .delete()
            .lt("created_at", cutoff.isoformat())
            .execute()
        )

    try:
        resp = await run_sync(_fn)
        deleted = len(resp.data or [])
        if deleted:
            logger.info(f"Retention: deleted {deleted} expired ride idempotency keys")
        return deleted
    except Exception as e:  # noqa: BLE001
        logger.warning(f"delete_expired_ride_idempotency_keys failed: {e}")
        return 0
