#include "character_status_overlay.h"

static const char *const g_character_names[EVA2_CHARACTER_COUNT] = {
    "真嗣", "明日香", "丽", "美里",
    "源堂", "冬月", "律子", "摩耶",
    "日向", "青叶", "加持", "洞木光",
    "冬二", "剑介", "渚薰", "Pen Pen",
};

static const char *const g_stat_labels[EVA2_CHARACTER_STAT_COUNT] = {
    "AT", "Impulse", "事务", "情报", "白兵", "同步",
    "饥饿", "水分", "困意", "如厕", "洗澡", "金钱",
};

void Eva2CharacterOverlayState_Init(Eva2CharacterOverlayState *state)
{
    if (!state) {
        return;
    }
    state->previous_buttons = 0;
    state->visible = 0;
    state->page = 0;
}

void Eva2CharacterOverlayState_Update(Eva2CharacterOverlayState *state, uint32_t buttons)
{
    uint32_t pressed;
    int combo_now;
    int combo_before;

    if (!state) {
        return;
    }

    pressed = buttons & ~state->previous_buttons;
    combo_now = (buttons & (EVA2_CHARACTER_BUTTON_L | EVA2_CHARACTER_BUTTON_R)) ==
        (EVA2_CHARACTER_BUTTON_L | EVA2_CHARACTER_BUTTON_R);
    combo_before =
        (state->previous_buttons & (EVA2_CHARACTER_BUTTON_L | EVA2_CHARACTER_BUTTON_R)) ==
        (EVA2_CHARACTER_BUTTON_L | EVA2_CHARACTER_BUTTON_R);

    if (combo_now && !combo_before) {
        state->visible = (uint8_t)!state->visible;
        if (state->visible) {
            state->page = 0;
        }
    } else if (state->visible && (pressed & EVA2_CHARACTER_BUTTON_L)) {
        state->page = state->page == 0
            ? (uint8_t)(EVA2_CHARACTER_PAGE_COUNT - 1)
            : (uint8_t)(state->page - 1);
    } else if (state->visible && (pressed & EVA2_CHARACTER_BUTTON_R)) {
        state->page = (uint8_t)((state->page + 1) % EVA2_CHARACTER_PAGE_COUNT);
    }

    state->previous_buttons = buttons;
}

const char *Eva2CharacterStatus_Name(size_t character_index)
{
    if (character_index >= EVA2_CHARACTER_COUNT) {
        return "";
    }
    return g_character_names[character_index];
}

const char *Eva2CharacterStatus_Label(Eva2CharacterStat stat)
{
    if ((unsigned)stat >= EVA2_CHARACTER_STAT_COUNT) {
        return "";
    }
    return g_stat_labels[stat];
}

size_t Eva2CharacterStatus_PageStart(uint8_t page)
{
    return (size_t)(page % EVA2_CHARACTER_PAGE_COUNT) * EVA2_CHARACTERS_PER_PAGE;
}

uint32_t Eva2CharacterStatus_Read(
    const volatile Eva2CharacterStats *character,
    Eva2CharacterStat stat)
{
    if (!character) {
        return 0;
    }

    switch (stat) {
    case EVA2_CHARACTER_STAT_AT:
        return character->at;
    case EVA2_CHARACTER_STAT_IMPULSE:
        return character->impulse;
    case EVA2_CHARACTER_STAT_TRANSACTION:
        return character->transaction;
    case EVA2_CHARACTER_STAT_INTELLIGENCE:
        return character->intelligence;
    case EVA2_CHARACTER_STAT_COMBAT:
        return character->combat;
    case EVA2_CHARACTER_STAT_SYNCHRONIZATION:
        return character->synchronization;
    case EVA2_CHARACTER_STAT_HUNGER:
        return character->hunger;
    case EVA2_CHARACTER_STAT_HYDRATION:
        return character->hydration;
    case EVA2_CHARACTER_STAT_SLEEPINESS:
        return character->sleepiness;
    case EVA2_CHARACTER_STAT_TOILET:
        return character->toilet;
    case EVA2_CHARACTER_STAT_BATHING:
        return character->bathing;
    case EVA2_CHARACTER_STAT_MONEY:
        return character->money;
    default:
        return 0;
    }
}

size_t Eva2CharacterStatus_FormatUint32(uint32_t value, char *buffer, size_t buffer_size)
{
    char reversed[10];
    size_t length = 0;
    size_t i;

    do {
        reversed[length++] = (char)('0' + value % 10u);
        value /= 10u;
    } while (value != 0);

    if (buffer_size != 0 && buffer) {
        size_t copy_length = length < buffer_size - 1 ? length : buffer_size - 1;
        for (i = 0; i < copy_length; ++i) {
            buffer[i] = reversed[length - i - 1];
        }
        buffer[copy_length] = '\0';
    }
    return length;
}
