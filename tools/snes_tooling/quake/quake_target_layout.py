"""ROM halfbank budgets for playback and geometry-only application targets."""
from dataclasses import dataclass, replace

from snes_tooling.quake.quake_alias_packing import STORAGE_PHYSICAL_HALFBANKS


@dataclass(frozen=True)
class AssetLayout:
    coordinate_first: int = 23
    coordinate_count: int = 3
    texture_count: int = 6
    lightmap_directory: int = 32
    lightmap_first: int = 33
    lightmap_count: int = 4
    unpack_code: int = 36
    pvs_count: int = 4
    face_owner_bank: int = 20
    spc_load_bank: int = 1
    weapon_data_bank: int = 6
    weapon_extra_bank: int = 7
    alias_halfbanks: tuple[int, ...] = STORAGE_PHYSICAL_HALFBANKS

    @property
    def lightmap_directory_address(self):
        return 0x8000 if self.lightmap_directory < 64 else 0

    @property
    def lightmap_directory_gsu_bank(self):
        return self.lightmap_directory if self.lightmap_directory < 64 else 0x60

    def linker_remaps(self):
        return {
            "SMPCODE": self.spc_load_bank,
            **({"BSP_WEAPON_DATA0": self.weapon_data_bank} if self.weapon_data_bank != 6 else {}),
            **({"BSP_WEAPON_DATA1": self.weapon_extra_bank} if self.weapon_extra_bank != 7 else {}),
            **{f"BSP_WORLD_TEXCOORD_{i}": self.coordinate_first + i
               for i in range(self.coordinate_count) if i != 2 or self.coordinate_count == 4},
            **{f"BSP_WORLD_TEXTURE_{i}": 26 + i for i in range(self.texture_count)},
            **{f"BSP_WORLD_PVS_{i}": 16 + i for i in range(self.pvs_count)},
            "BSP_WORLD_FACE_OWNERS": self.face_owner_bank,
            "BSP_WORLD_LIGHTMAP_DIRECTORY": self.lightmap_directory,
            **{f"BSP_WORLD_LIGHTMAP_{i}": self.lightmap_first + i for i in range(self.lightmap_count)},
            "GSU_LIGHTMAP_UNPACK_ROM_CODE": self.unpack_code,
            "F3_GSU_LIGHTMAP_UNPACK_ROM_CODE": self.unpack_code,
            **{f"BSP_ALIAS_{i}": bank for i, bank in enumerate(self.alias_halfbanks)
               if i >= len(STORAGE_PHYSICAL_HALFBANKS) or bank != STORAGE_PHYSICAL_HALFBANKS[i]},
        }


def asset_layout(playback: bool, map_entry: str | None = None) -> AssetLayout:
    # Fly uses the old alias overflow banks for full map materials.
    # Its composed-cache banks are idle and can store the gameplay actors.
    # Eighteen Fly alias banks leave ROM63 free for world face owners.
    # Fly has no demo soundtrack, so the two halves of CPU bank $C2
    # can hold the full gameplay SPC image for one IPL transfer.
    if playback:
        return AssetLayout()
    fly = AssetLayout(coordinate_first=59, coordinate_count=4, texture_count=12,
                      lightmap_directory=64, lightmap_first=55, unpack_code=23,
                      pvs_count=5, face_owner_bank=63, spc_load_bank=100,
                      alias_halfbanks=tuple(range(87, 94)) + tuple(range(66, 77)))
    if map_entry == "maps/e1m1.bsp":
        # The actor atlas and expanded stock weapon rows occupy unused composed-cache banks.
        return replace(fly, alias_halfbanks=fly.alias_halfbanks + tuple(range(77, 86)),
                       weapon_data_bank=86, weapon_extra_bank=103)
    if map_entry == "maps/e1m4.bsp":
        return replace(fly, coordinate_first=60, face_owner_bank=12, lightmap_count=5,
                       weapon_data_bank=13)
    if map_entry == "maps/e1m2.bsp":
        return replace(fly, weapon_data_bank=86, weapon_extra_bank=103)
    return fly


def alias_halfbank_limit(target, storage):
    """Account for E1M1 Fly's additional idle banks on the extended GSU mapping."""
    e1m1 = asset_layout(False, "maps/e1m1.bsp").alias_halfbanks
    if target.max_gsu_rom_bank >= 0x6e and tuple(storage) == e1m1[:len(storage)] and len(storage) > 18:
        return len(e1m1)
    return target.max_alias_halfbank_count
