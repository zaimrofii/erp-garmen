// REAL - settings devices (F5.4.CLOSE / backend B28). GET `/settings/devices/`.
//
// Ini **katalog profil** (`core_device_profile.DeviceProfile`), bukan binding
// (`/devices/me|bind|unbind` yang sudah REAL sejak Fase G). Pemetaan B28 (Opsi A):
//
//   * `device_type` ← `DeviceProfile.code` (`OPERATOR_HP`/`KIOSK_TABLET`/`SCANNER_USB`/
//     `DESKTOP`) → dipetakan ke `code` pada tipe UI `DeviceProfile`;
//   * `label` ← `DeviceProfile.name`; `active` ← `is_active`; `config` = JSON profil;
//   * `binding_count` = jumlah `DeviceBinding` yang memakai profil (aditif, monitoring);
//   * `wc_code`/`last_seen_at` **tidak ada** di baris (milik `DeviceBinding`) — filter
//     `?wc_code=` tetap didukung backend.
import type { ApiClient } from '@/integrations/api-client';
import type { DeviceProfile } from '@/types/settings';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readBool,
  readListPage,
  readNum,
  readStr,
  type ListPage,
} from './_shape';

export const SETTINGS_DEVICES_PATH = '/settings/devices/';

export interface DeviceProfileRow {
  id: number;
  /** `DeviceProfile.code` (`OPERATOR_HP`…). */
  device_type: string;
  label: string;
  description: string;
  active: boolean;
  config: Record<string, unknown>;
  binding_count: number;
}

export interface SettingsDevicesParams {
  deviceType?: string | null;
  wcCode?: string | null;
  active?: boolean | null;
  limit?: number | null;
  cursor?: number | null;
}

/** PURE — satu baris backend → `DeviceProfileRow`. */
export function readDeviceProfileRow(raw: unknown): DeviceProfileRow | null {
  if (!isRecord(raw)) return null;
  const config = raw['config'];

  return {
    id: readNum(raw['id']),
    device_type: readStr(raw['device_type']),
    label: readStr(raw['label']),
    description: readStr(raw['description']),
    active: readBool(raw['active']),
    config: isRecord(config) ? config : {},
    binding_count: readNum(raw['binding_count']),
  };
}

/** PURE — respons ListPage device profile. */
export function readDeviceProfilePage(raw: unknown): ListPage<DeviceProfileRow> | null {
  return readListPage<DeviceProfileRow>(raw, readDeviceProfileRow);
}

/** PURE — baris backend → tipe UI `DeviceProfile` (`code` ← `device_type`). */
export function toDeviceProfile(row: DeviceProfileRow): DeviceProfile {
  return {
    id: row.id,
    code: row.device_type,
    label: row.label,
    description: row.description,
  };
}

/** PURE — path + `?device_type=&wc_code=&active=&limit=&cursor=`. */
export function buildSettingsDevicesPath(params: SettingsDevicesParams = {}): string {
  return buildQueryPath(SETTINGS_DEVICES_PATH, {
    device_type: params.deviceType,
    wc_code: params.wcCode,
    active: params.active === null || params.active === undefined ? null : params.active,
    limit: params.limit,
    cursor: params.cursor,
  });
}

/** Baris mentah (butuh `binding_count`/`config`/`active`) + amplop ListPage. */
export async function fetchDeviceProfileRows(
  client: ApiClient,
  params: SettingsDevicesParams = {},
): Promise<ListPage<DeviceProfileRow>> {
  return getParsed(
    client,
    buildSettingsDevicesPath(params),
    readDeviceProfilePage,
    'katalog device profile',
  );
}

/** Katalog profil sebagai tipe UI `DeviceProfile[]` (DeviceProfilesPage). */
export async function fetchDeviceProfiles(
  client: ApiClient,
  params: SettingsDevicesParams = {},
): Promise<DeviceProfile[]> {
  const page = await fetchDeviceProfileRows(client, params);

  return page.rows.map(toDeviceProfile);
}
