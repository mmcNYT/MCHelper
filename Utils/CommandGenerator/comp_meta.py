# -*- coding: utf-8 -*-
"""CommandGenerator：数据组件**字段元数据**（自动生成，勿手改）。

生成脚本：.temp/gen_comp_meta.py
来源：1.21.11 反编译各组件 CODEC 的 RecordCodecBuilder
      .group(... fieldOf("key") ...)

COMP_META[组件id] = {
    'type':   值类型（含泛型，原文）
    'kind':   compound | map | list | scalar | holder | unit
    'fields': [{'key','codec','optional','default'}, ...]
              （仅 kind=compound 时有意义）
    'file':   来源文件（便于复查）
}
"""

COMP_META = {
    "attack_range": {
        "type": 'AttackRange',
        "kind": "compound",
        "codec": 'AttackRange.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/AttackRange.java",
        "fields": [
            {"key": "min_reach", "codec": 'ExtraCodecs.floatRange(0.0F, 64.0F)', "optional": True, "default": '0.0F'},
            {"key": "max_reach", "codec": 'ExtraCodecs.floatRange(0.0F, 64.0F)', "optional": True, "default": '3.0F'},
            {"key": "min_creative_reach", "codec": 'ExtraCodecs.floatRange(0.0F, 64.0F)', "optional": True, "default": '0.0F'},
            {"key": "max_creative_reach", "codec": 'ExtraCodecs.floatRange(0.0F, 64.0F)', "optional": True, "default": '5.0F'},
            {"key": "hitbox_margin", "codec": 'ExtraCodecs.floatRange(0.0F, 1.0F)', "optional": True, "default": '0.3F'},
            {"key": "mob_factor", "codec": 'Codec.floatRange(0.0F, 2.0F)', "optional": True, "default": '1.0F'},
        ],
    },
    "attribute_modifiers": {
        "type": 'ItemAttributeModifiers',
        "kind": "list",
        "codec": 'ItemAttributeModifiers.CODEC',
        "note": '列表',
        "file": "net/minecraft/world/item/component/ItemAttributeModifiers.java",
        "fields": [
        ],
    },
    "banner_patterns": {
        "type": 'BannerPatternLayers',
        "kind": "list",
        "codec": 'BannerPatternLayers.CODEC',
        "note": '列表',
        "file": "net/minecraft/world/level/block/entity/BannerPatternLayers.java",
        "fields": [
        ],
    },
    "base_color": {
        "type": 'DyeColor',
        "kind": "enum_string",
        "codec": 'DyeColor.CODEC',
        "note": '单值包装（无字段）',
        "file": "net/minecraft/world/item/DyeColor.java",
        "fields": [
        ],
    },
    "bees": {
        "type": 'Bees',
        "kind": "list",
        "codec": 'Bees.CODEC',
        "note": '单值包装（无字段）',
        "file": "net/minecraft/world/item/component/Bees.java",
        "fields": [
        ],
    },
    "block_entity_data": {
        "type": 'TypedEntityData<BlockEntityType<?>>',
        "kind": "nbt",
        "codec": 'TypedEntityData.codec(BuiltInRegistries.BLOCK_ENTITY_TYPE.byNameCodec())',
        "note": '单值包装（无字段）',
        "file": "net/minecraft/world/item/component/TypedEntityData.java",
        "fields": [
        ],
    },
    "block_state": {
        "type": 'BlockItemStateProperties',
        "kind": "map",
        "codec": 'BlockItemStateProperties.CODEC',
        "note": '键值映射',
        "file": "net/minecraft/world/item/component/BlockItemStateProperties.java",
        "fields": [
        ],
    },
    "blocks_attacks": {
        "type": 'BlocksAttacks',
        "kind": "compound",
        "codec": 'BlocksAttacks.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/BlocksAttacks.java",
        "fields": [
            {"key": "block_delay_seconds", "codec": 'ExtraCodecs.NON_NEGATIVE_FLOAT', "optional": True, "default": '0.0F'},
            {"key": "disable_cooldown_scale", "codec": 'ExtraCodecs.NON_NEGATIVE_FLOAT', "optional": True, "default": '1.0F'},
            {"key": "damage_reductions", "codec": '', "optional": True, "default": 'List.of(new BlocksAttacks.DamageReduction(90.0F, Optional.empty('},
            {"key": "item_damage", "codec": '', "optional": True, "default": 'BlocksAttacks.ItemDamageFunction.DEFAULT'},
            {"key": "bypassed_by", "codec": 'TagKey.hashedCodec(Registries.DAMAGE_TYPE)', "optional": True, "default": None},
            {"key": "block_sound", "codec": 'SoundEvent.CODEC', "optional": True, "default": None},
            {"key": "disabled_sound", "codec": 'SoundEvent.CODEC', "optional": True, "default": None},
        ],
    },
    "break_sound": {
        "type": 'Holder<SoundEvent>',
        "kind": "holder",
        "codec": 'SoundEvent.CODEC',
        "note": '单值包装（无字段）',
        "file": "net/minecraft/core/Holder.java",
        "fields": [
        ],
    },
    "bucket_entity_data": {
        "type": 'CustomData',
        "kind": "nbt",
        "codec": 'CustomData.CODEC',
        "note": '单值包装（无字段）',
        "file": "net/minecraft/world/item/component/CustomData.java",
        "fields": [
        ],
    },
    "bundle_contents": {
        "type": 'BundleContents',
        "kind": "list",
        "codec": 'BundleContents.CODEC',
        "note": '列表',
        "file": "net/minecraft/world/item/component/BundleContents.java",
        "fields": [
        ],
    },
    "can_break": {
        "type": 'AdventureModePredicate',
        "kind": "list",
        "codec": 'AdventureModePredicate.CODEC',
        "note": '列表',
        "file": "net/minecraft/world/item/AdventureModePredicate.java",
        "fields": [
        ],
    },
    "can_place_on": {
        "type": 'AdventureModePredicate',
        "kind": "list",
        "codec": 'AdventureModePredicate.CODEC',
        "note": '列表',
        "file": "net/minecraft/world/item/AdventureModePredicate.java",
        "fields": [
        ],
    },
    "charged_projectiles": {
        "type": 'ChargedProjectiles',
        "kind": "list",
        "codec": 'ChargedProjectiles.CODEC',
        "note": '列表',
        "file": "net/minecraft/world/item/component/ChargedProjectiles.java",
        "fields": [
        ],
    },
    "consumable": {
        "type": 'Consumable',
        "kind": "compound",
        "codec": 'Consumable.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/Consumable.java",
        "fields": [
            {"key": "consume_seconds", "codec": 'ExtraCodecs.NON_NEGATIVE_FLOAT', "optional": True, "default": '1.6F'},
            {"key": "animation", "codec": 'ItemUseAnimation.CODEC', "optional": True, "default": 'ItemUseAnimation.EAT'},
            {"key": "sound", "codec": 'SoundEvent.CODEC', "optional": True, "default": 'SoundEvents.GENERIC_EAT'},
            {"key": "has_consume_particles", "codec": 'Codec.BOOL', "optional": True, "default": 'true'},
            {"key": "on_consume_effects", "codec": 'ConsumeEffect.CODEC.listOf()', "optional": True, "default": 'List.of('},
        ],
    },
    "container": {
        "type": 'ItemContainerContents',
        "kind": "list",
        "codec": 'ItemContainerContents.CODEC',
        "note": '单值包装（无字段）',
        "file": "net/minecraft/world/item/component/ItemContainerContents.java",
        "fields": [
        ],
    },
    "container_loot": {
        "type": 'SeededContainerLoot',
        "kind": "compound",
        "codec": 'SeededContainerLoot.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/SeededContainerLoot.java",
        "fields": [
            {"key": "loot_table", "codec": 'LootTable.KEY_CODEC', "optional": False, "default": None},
            {"key": "seed", "codec": 'Codec.LONG', "optional": True, "default": '0L'},
        ],
    },
    "creative_slot_lock": {
        "type": 'Unit',
        "kind": "unit",
        "codec": '',
        "note": '无值',
        "file": "net/minecraft/util/Unit.java",
        "fields": [
        ],
    },
    "custom_data": {
        "type": 'CustomData',
        "kind": "nbt",
        "codec": 'CustomData.CODEC',
        "note": '单值包装（无字段）',
        "file": "net/minecraft/world/item/component/CustomData.java",
        "fields": [
        ],
    },
    "custom_model_data": {
        "type": 'CustomModelData',
        "kind": "compound",
        "codec": 'CustomModelData.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/CustomModelData.java",
        "fields": [
            {"key": "floats", "codec": 'Codec.FLOAT.listOf()', "optional": True, "default": 'List.of('},
            {"key": "flags", "codec": 'Codec.BOOL.listOf()', "optional": True, "default": 'List.of('},
            {"key": "strings", "codec": 'Codec.STRING.listOf()', "optional": True, "default": 'List.of('},
            {"key": "colors", "codec": 'ExtraCodecs.RGB_COLOR_CODEC.listOf()', "optional": True, "default": 'List.of('},
        ],
    },
    "custom_name": {
        "type": 'Component',
        "kind": "text",
        "codec": 'ComponentSerialization.CODEC',
        "note": '单值包装（无字段）',
        "file": "net/minecraft/network/chat/Component.java",
        "fields": [
        ],
    },
    "damage": {
        "type": 'Integer',
        "kind": "scalar",
        "codec": 'ExtraCodecs.NON_NEGATIVE_INT',
        "note": '',
        "file": "",
        "fields": [
        ],
    },
    "damage_resistant": {
        "type": 'DamageResistant',
        "kind": "compound",
        "codec": 'DamageResistant.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/DamageResistant.java",
        "fields": [
            {"key": "types", "codec": 'TagKey.hashedCodec(Registries.DAMAGE_TYPE)', "optional": False, "default": None},
        ],
    },
    "damage_type": {
        "type": 'EitherHolder<DamageType>',
        "kind": "holder",
        "codec": 'EitherHolder.codec(Registries.DAMAGE_TYPE, DamageType.CODEC)',
        "note": '单值包装（无字段）',
        "file": "net/minecraft/world/item/EitherHolder.java",
        "fields": [
        ],
    },
    "death_protection": {
        "type": 'DeathProtection',
        "kind": "compound",
        "codec": 'DeathProtection.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/DeathProtection.java",
        "fields": [
            {"key": "death_effects", "codec": 'ConsumeEffect.CODEC.listOf()', "optional": True, "default": 'List.of('},
        ],
    },
    "debug_stick_state": {
        "type": 'DebugStickState',
        "kind": "scalar",
        "codec": 'DebugStickState.CODEC',
        "note": '字符串',
        "file": "net/minecraft/world/item/component/DebugStickState.java",
        "fields": [
        ],
    },
    "dyed_color": {
        "type": 'DyedItemColor',
        "kind": "scalar",
        "codec": 'DyedItemColor.CODEC',
        "note": '整数',
        "file": "net/minecraft/world/item/component/DyedItemColor.java",
        "fields": [
        ],
    },
    "enchantable": {
        "type": 'Enchantable',
        "kind": "compound",
        "codec": 'Enchantable.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/enchantment/Enchantable.java",
        "fields": [
            {"key": "value", "codec": 'ExtraCodecs.POSITIVE_INT', "optional": False, "default": None},
        ],
    },
    "enchantment_glint_override": {
        "type": 'Boolean',
        "kind": "scalar",
        "codec": 'Codec.BOOL',
        "note": '',
        "file": "",
        "fields": [
        ],
    },
    "enchantments": {
        "type": 'ItemEnchantments',
        "kind": "map",
        "codec": 'ItemEnchantments.CODEC',
        "note": '键值映射',
        "file": "net/minecraft/world/item/enchantment/ItemEnchantments.java",
        "fields": [
        ],
    },
    "entity_data": {
        "type": 'TypedEntityData<EntityType<?>>',
        "kind": "nbt",
        "codec": 'TypedEntityData.codec(EntityType.CODEC)',
        "note": '单值包装（无字段）',
        "file": "net/minecraft/world/item/component/TypedEntityData.java",
        "fields": [
        ],
    },
    "equippable": {
        "type": 'Equippable',
        "kind": "compound",
        "codec": 'Equippable.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/equipment/Equippable.java",
        "fields": [
            {"key": "slot", "codec": 'EquipmentSlot.CODEC', "optional": False, "default": None},
            {"key": "equip_sound", "codec": 'SoundEvent.CODEC', "optional": True, "default": 'SoundEvents.ARMOR_EQUIP_GENERIC'},
            {"key": "asset_id", "codec": 'ResourceKey.codec(EquipmentAssets.ROOT_ID)', "optional": True, "default": None},
            {"key": "camera_overlay", "codec": 'Identifier.CODEC', "optional": True, "default": None},
            {"key": "allowed_entities", "codec": 'RegistryCodecs.homogeneousList(Registries.ENTITY_TYPE)', "optional": True, "default": None},
            {"key": "dispensable", "codec": 'Codec.BOOL', "optional": True, "default": 'true'},
            {"key": "swappable", "codec": 'Codec.BOOL', "optional": True, "default": 'true'},
            {"key": "damage_on_hurt", "codec": 'Codec.BOOL', "optional": True, "default": 'true'},
            {"key": "equip_on_interact", "codec": 'Codec.BOOL', "optional": True, "default": 'false'},
            {"key": "can_be_sheared", "codec": 'Codec.BOOL', "optional": True, "default": 'false'},
            {"key": "shearing_sound", "codec": '', "optional": True, "default": 'BuiltInRegistries.SOUND_EVENT.wrapAsHolder(SoundEvents.SHEARS_SNIP'},
        ],
    },
    "firework_explosion": {
        "type": 'FireworkExplosion',
        "kind": "compound",
        "codec": 'FireworkExplosion.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/FireworkExplosion.java",
        "fields": [
            {"key": "shape", "codec": 'FireworkExplosion.Shape.CODEC', "optional": False, "default": None},
            {"key": "colors", "codec": 'COLOR_LIST_CODEC', "optional": True, "default": 'IntList.of('},
            {"key": "fade_colors", "codec": 'COLOR_LIST_CODEC', "optional": True, "default": 'IntList.of('},
            {"key": "has_trail", "codec": 'Codec.BOOL', "optional": True, "default": 'false'},
            {"key": "has_twinkle", "codec": 'Codec.BOOL', "optional": True, "default": 'false'},
        ],
    },
    "fireworks": {
        "type": 'Fireworks',
        "kind": "compound",
        "codec": 'Fireworks.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/Fireworks.java",
        "fields": [
            {"key": "flight_duration", "codec": 'ExtraCodecs.UNSIGNED_BYTE', "optional": True, "default": '0'},
            {"key": "explosions", "codec": 'FireworkExplosion.CODEC.sizeLimitedListOf(256)', "optional": True, "default": 'List.of('},
        ],
    },
    "food": {
        "type": 'FoodProperties',
        "kind": "compound",
        "codec": 'FoodProperties.DIRECT_CODEC',
        "note": '（未定位到顶层 CODEC，退回全文解析）',
        "file": "net/minecraft/world/food/FoodProperties.java",
        "fields": [
            {"key": "nutrition", "codec": 'ExtraCodecs.NON_NEGATIVE_INT', "optional": False, "default": None},
            {"key": "saturation", "codec": 'Codec.FLOAT', "optional": False, "default": None},
            {"key": "can_always_eat", "codec": 'Codec.BOOL', "optional": True, "default": 'false'},
        ],
    },
    "glider": {
        "type": 'Unit',
        "kind": "unit",
        "codec": 'Unit.CODEC',
        "note": '无值',
        "file": "net/minecraft/util/Unit.java",
        "fields": [
        ],
    },
    "instrument": {
        "type": 'InstrumentComponent',
        "kind": "holder",
        "codec": 'InstrumentComponent.CODEC',
        "note": '资源',
        "file": "net/minecraft/world/item/component/InstrumentComponent.java",
        "fields": [
        ],
    },
    "intangible_projectile": {
        "type": 'Unit',
        "kind": "unit",
        "codec": 'Unit.CODEC',
        "note": '无值',
        "file": "net/minecraft/util/Unit.java",
        "fields": [
        ],
    },
    "item_model": {
        "type": 'Identifier',
        "kind": "scalar",
        "codec": 'Identifier.CODEC',
        "note": '字符串',
        "file": "net/minecraft/resources/Identifier.java",
        "fields": [
        ],
    },
    "item_name": {
        "type": 'Component',
        "kind": "text",
        "codec": 'ComponentSerialization.CODEC',
        "note": '单值包装（无字段）',
        "file": "net/minecraft/network/chat/Component.java",
        "fields": [
        ],
    },
    "jukebox_playable": {
        "type": 'JukeboxPlayable',
        "kind": "holder",
        "codec": 'JukeboxPlayable.CODEC',
        "note": '资源',
        "file": "net/minecraft/world/item/JukeboxPlayable.java",
        "fields": [
        ],
    },
    "kinetic_weapon": {
        "type": 'KineticWeapon',
        "kind": "compound",
        "codec": 'KineticWeapon.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/KineticWeapon.java",
        "fields": [
            {"key": "contact_cooldown_ticks", "codec": 'ExtraCodecs.NON_NEGATIVE_INT', "optional": True, "default": '10'},
            {"key": "delay_ticks", "codec": 'ExtraCodecs.NON_NEGATIVE_INT', "optional": True, "default": '0'},
            {"key": "dismount_conditions", "codec": 'KineticWeapon.Condition.CODEC', "optional": True, "default": None},
            {"key": "knockback_conditions", "codec": 'KineticWeapon.Condition.CODEC', "optional": True, "default": None},
            {"key": "damage_conditions", "codec": 'KineticWeapon.Condition.CODEC', "optional": True, "default": None},
            {"key": "forward_movement", "codec": 'Codec.FLOAT', "optional": True, "default": '0.0F'},
            {"key": "damage_multiplier", "codec": 'Codec.FLOAT', "optional": True, "default": '1.0F'},
            {"key": "sound", "codec": 'SoundEvent.CODEC', "optional": True, "default": None},
            {"key": "hit_sound", "codec": 'SoundEvent.CODEC', "optional": True, "default": None},
        ],
    },
    "lock": {
        "type": 'LockCode',
        "kind": "compound",
        "codec": 'LockCode.CODEC',
        "note": '',
        "file": "net/minecraft/world/LockCode.java",
        "fields": [
        ],
    },
    "lodestone_tracker": {
        "type": 'LodestoneTracker',
        "kind": "compound",
        "codec": 'LodestoneTracker.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/LodestoneTracker.java",
        "fields": [
            {"key": "target", "codec": 'GlobalPos.CODEC', "optional": True, "default": None},
            {"key": "tracked", "codec": 'Codec.BOOL', "optional": True, "default": 'true'},
        ],
    },
    "lore": {
        "type": 'ItemLore',
        "kind": "textlines",
        "codec": 'ItemLore.CODEC',
        "note": '单值包装（无字段）',
        "file": "net/minecraft/world/item/component/ItemLore.java",
        "fields": [
        ],
    },
    "map_color": {
        "type": 'MapItemColor',
        "kind": "scalar",
        "codec": 'MapItemColor.CODEC',
        "note": '整数',
        "file": "net/minecraft/world/item/component/MapItemColor.java",
        "fields": [
        ],
    },
    "map_decorations": {
        "type": 'MapDecorations',
        "kind": "map",
        "codec": 'MapDecorations.CODEC',
        "note": '键值映射',
        "file": "net/minecraft/world/item/component/MapDecorations.java",
        "fields": [
        ],
    },
    "map_id": {
        "type": 'MapId',
        "kind": "scalar",
        "codec": 'MapId.CODEC',
        "note": '整数',
        "file": "net/minecraft/world/level/saveddata/maps/MapId.java",
        "fields": [
        ],
    },
    "map_post_processing": {
        "type": 'MapPostProcessing',
        "kind": "enum_string",
        "codec": '',
        "note": '单值包装（无字段）',
        "file": "net/minecraft/world/item/component/MapPostProcessing.java",
        "fields": [
        ],
    },
    "max_damage": {
        "type": 'Integer',
        "kind": "scalar",
        "codec": 'ExtraCodecs.POSITIVE_INT',
        "note": '',
        "file": "",
        "fields": [
        ],
    },
    "max_stack_size": {
        "type": 'Integer',
        "kind": "scalar",
        "codec": 'ExtraCodecs.intRange(1, 99)',
        "note": '',
        "file": "",
        "fields": [
        ],
    },
    "minimum_attack_charge": {
        "type": 'Float',
        "kind": "scalar",
        "codec": 'ExtraCodecs.floatRange(0.0F, 1.0F)',
        "note": '',
        "file": "",
        "fields": [
        ],
    },
    "note_block_sound": {
        "type": 'Identifier',
        "kind": "scalar",
        "codec": 'Identifier.CODEC',
        "note": '字符串',
        "file": "net/minecraft/resources/Identifier.java",
        "fields": [
        ],
    },
    "ominous_bottle_amplifier": {
        "type": 'OminousBottleAmplifier',
        "kind": "scalar",
        "codec": 'OminousBottleAmplifier.CODEC',
        "note": '单值包装（无字段）',
        "file": "net/minecraft/world/item/component/OminousBottleAmplifier.java",
        "fields": [
        ],
    },
    "piercing_weapon": {
        "type": 'PiercingWeapon',
        "kind": "compound",
        "codec": 'PiercingWeapon.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/PiercingWeapon.java",
        "fields": [
            {"key": "deals_knockback", "codec": 'Codec.BOOL', "optional": True, "default": 'true'},
            {"key": "dismounts", "codec": 'Codec.BOOL', "optional": True, "default": 'false'},
            {"key": "sound", "codec": 'SoundEvent.CODEC', "optional": True, "default": None},
            {"key": "hit_sound", "codec": 'SoundEvent.CODEC', "optional": True, "default": None},
        ],
    },
    "pot_decorations": {
        "type": 'PotDecorations',
        "kind": "list",
        "codec": 'PotDecorations.CODEC',
        "note": '单值包装（无字段）',
        "file": "net/minecraft/world/level/block/entity/PotDecorations.java",
        "fields": [
        ],
    },
    "potion_contents": {
        "type": 'PotionContents',
        "kind": "list",
        "codec": 'PotionContents.CODEC',
        "note": '列表',
        "file": "net/minecraft/world/item/alchemy/PotionContents.java",
        "fields": [
        ],
    },
    "potion_duration_scale": {
        "type": 'Float',
        "kind": "scalar",
        "codec": 'ExtraCodecs.NON_NEGATIVE_FLOAT',
        "note": '',
        "file": "",
        "fields": [
        ],
    },
    "profile": {
        "type": 'ResolvableProfile',
        "kind": "compound",
        "codec": 'ResolvableProfile.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/ResolvableProfile.java",
        "fields": [
        ],
    },
    "provides_banner_patterns": {
        "type": 'TagKey<BannerPattern>',
        "kind": "scalar",
        "codec": 'TagKey.hashedCodec(Registries.BANNER_PATTERN)',
        "note": '字符串',
        "file": "net/minecraft/tags/TagKey.java",
        "fields": [
        ],
    },
    "provides_trim_material": {
        "type": 'ProvidesTrimMaterial',
        "kind": "holder",
        "codec": 'ProvidesTrimMaterial.CODEC',
        "note": '资源',
        "file": "net/minecraft/world/item/component/ProvidesTrimMaterial.java",
        "fields": [
        ],
    },
    "rarity": {
        "type": 'Rarity',
        "kind": "enum_string",
        "codec": 'Rarity.CODEC',
        "note": '单值包装（无字段）',
        "file": "net/minecraft/world/item/Rarity.java",
        "fields": [
        ],
    },
    "recipes": {
        "type": 'List<ResourceKey<Recipe<?>>>',
        "kind": "list",
        "codec": 'Recipe.KEY_CODEC.listOf()',
        "note": '',
        "file": "",
        "fields": [
        ],
    },
    "repair_cost": {
        "type": 'Integer',
        "kind": "scalar",
        "codec": 'ExtraCodecs.NON_NEGATIVE_INT',
        "note": '',
        "file": "",
        "fields": [
        ],
    },
    "repairable": {
        "type": 'Repairable',
        "kind": "compound",
        "codec": 'Repairable.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/enchantment/Repairable.java",
        "fields": [
            {"key": "items", "codec": 'RegistryCodecs.homogeneousList(Registries.ITEM)', "optional": False, "default": None},
        ],
    },
    "stored_enchantments": {
        "type": 'ItemEnchantments',
        "kind": "map",
        "codec": 'ItemEnchantments.CODEC',
        "note": '键值映射',
        "file": "net/minecraft/world/item/enchantment/ItemEnchantments.java",
        "fields": [
        ],
    },
    "suspicious_stew_effects": {
        "type": 'SuspiciousStewEffects',
        "kind": "list",
        "codec": 'SuspiciousStewEffects.CODEC',
        "note": '列表',
        "file": "net/minecraft/world/item/component/SuspiciousStewEffects.java",
        "fields": [
        ],
    },
    "swing_animation": {
        "type": 'SwingAnimation',
        "kind": "compound",
        "codec": 'SwingAnimation.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/SwingAnimation.java",
        "fields": [
            {"key": "type", "codec": 'SwingAnimationType.CODEC', "optional": True, "default": 'DEFAULT.type'},
            {"key": "duration", "codec": 'ExtraCodecs.POSITIVE_INT', "optional": True, "default": 'DEFAULT.duration'},
        ],
    },
    "tool": {
        "type": 'Tool',
        "kind": "compound",
        "codec": 'Tool.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/Tool.java",
        "fields": [
            {"key": "rules", "codec": 'Tool.Rule.CODEC.listOf()', "optional": False, "default": None},
            {"key": "default_mining_speed", "codec": 'Codec.FLOAT', "optional": True, "default": '1.0F'},
            {"key": "damage_per_block", "codec": 'ExtraCodecs.NON_NEGATIVE_INT', "optional": True, "default": '1'},
            {"key": "can_destroy_blocks_in_creative", "codec": 'Codec.BOOL', "optional": True, "default": 'true'},
        ],
    },
    "tooltip_display": {
        "type": 'TooltipDisplay',
        "kind": "compound",
        "codec": 'TooltipDisplay.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/TooltipDisplay.java",
        "fields": [
            {"key": "hide_tooltip", "codec": 'Codec.BOOL', "optional": True, "default": 'false'},
            {"key": "hidden_components", "codec": 'COMPONENT_SET_CODEC', "optional": True, "default": 'ReferenceSortedSets.emptySet('},
        ],
    },
    "tooltip_style": {
        "type": 'Identifier',
        "kind": "scalar",
        "codec": 'Identifier.CODEC',
        "note": '字符串',
        "file": "net/minecraft/resources/Identifier.java",
        "fields": [
        ],
    },
    "trim": {
        "type": 'ArmorTrim',
        "kind": "compound",
        "codec": 'ArmorTrim.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/equipment/trim/ArmorTrim.java",
        "fields": [
            {"key": "material", "codec": 'TrimMaterial.CODEC', "optional": False, "default": None},
            {"key": "pattern", "codec": 'TrimPattern.CODEC', "optional": False, "default": None},
        ],
    },
    "unbreakable": {
        "type": 'Unit',
        "kind": "unit",
        "codec": 'Unit.CODEC',
        "note": '无值',
        "file": "net/minecraft/util/Unit.java",
        "fields": [
        ],
    },
    "use_cooldown": {
        "type": 'UseCooldown',
        "kind": "compound",
        "codec": 'UseCooldown.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/UseCooldown.java",
        "fields": [
            {"key": "seconds", "codec": 'ExtraCodecs.POSITIVE_FLOAT', "optional": False, "default": None},
            {"key": "cooldown_group", "codec": 'Identifier.CODEC', "optional": True, "default": None},
        ],
    },
    "use_effects": {
        "type": 'UseEffects',
        "kind": "compound",
        "codec": 'UseEffects.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/UseEffects.java",
        "fields": [
            {"key": "can_sprint", "codec": 'Codec.BOOL', "optional": True, "default": 'DEFAULT.canSprint'},
            {"key": "interact_vibrations", "codec": 'Codec.BOOL', "optional": True, "default": 'DEFAULT.interactVibrations'},
            {"key": "speed_multiplier", "codec": 'Codec.floatRange(0.0F, 1.0F)', "optional": True, "default": 'DEFAULT.speedMultiplier'},
        ],
    },
    "use_remainder": {
        "type": 'UseRemainder',
        "kind": "compound",
        "codec": 'UseRemainder.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/UseRemainder.java",
        "fields": [
        ],
    },
    "weapon": {
        "type": 'Weapon',
        "kind": "compound",
        "codec": 'Weapon.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/Weapon.java",
        "fields": [
            {"key": "item_damage_per_attack", "codec": 'ExtraCodecs.NON_NEGATIVE_INT', "optional": True, "default": '1'},
            {"key": "disable_blocking_for_seconds", "codec": 'ExtraCodecs.NON_NEGATIVE_FLOAT', "optional": True, "default": '0.0F'},
        ],
    },
    "writable_book_content": {
        "type": 'WritableBookContent',
        "kind": "compound",
        "codec": 'WritableBookContent.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/WritableBookContent.java",
        "fields": [
            {"key": "pages", "codec": 'PAGES_CODEC', "optional": True, "default": 'List.of('},
        ],
    },
    "written_book_content": {
        "type": 'WrittenBookContent',
        "kind": "compound",
        "codec": 'WrittenBookContent.CODEC',
        "note": '',
        "file": "net/minecraft/world/item/component/WrittenBookContent.java",
        "fields": [
            {"key": "title", "codec": '', "optional": False, "default": None},
            {"key": "author", "codec": 'Codec.STRING', "optional": False, "default": None},
            {"key": "generation", "codec": 'ExtraCodecs.intRange(0, 3)', "optional": True, "default": '0'},
            {"key": "pages", "codec": 'PAGES_CODEC', "optional": True, "default": 'List.of('},
            {"key": "resolved", "codec": 'Codec.BOOL', "optional": True, "default": 'false'},
        ],
    },
}

# 已由 give.py 手工实现（专用语义/版本分支）的组件
MANUAL = ['attribute_modifiers', 'custom_model_data', 'custom_name', 'dyed_color', 'enchantments', 'item_name', 'jukebox_playable', 'lore', 'stored_enchantments', 'tooltip_display', 'unbreakable']

