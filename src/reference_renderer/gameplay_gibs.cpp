#include "gameplay_internal.hpp"

namespace quake_bsp_reference {

void GameplaySession::Impl::gib_capture(bool head)
{
    const auto actor = global("SELF");
    const auto source = head ? actor : gw(constant("QC_GRUNT_DROP"));
    unsigned record = gib_records;
    if (!head)
    {
        for (record += gib_size; record < 512 && e(actor, record); record += gib_size)
            ;
        if (record >= 512)
            throw std::runtime_error("stock death spawned more than three fragments");
    }
    unsigned model = 0;
    while (model < 5 && field(source, "MODEL") != constant("QC_GIB_MODEL_" + std::to_string(model)))
        ++model;
    if (model == 5)
        throw std::runtime_error("unbound overkill model");
    e(actor, record) = head ? 0xffff : gw(field(source, "NEXTTHINK") - global("TIME"));
    e(actor, record + gib_row) = gw(constant("QC_GIB_FIRST_ROW") + model) | (head ? 0x8000 : 0);
    for (unsigned axis = 0; axis < 3; ++axis)
    {
        e(actor, record + gib_origin + axis * 2) = field(source, "ORIGIN", axis);
        e(actor, record + gib_velocity + axis * 2) = field(source, "VELOCITY", axis);
        e(actor, record + gib_angles + axis * 2) = head ? field(source, "ANGLES", axis) : 0;
        e(actor, record + gib_spin + axis * 2) = field(source, "AVELOCITY", axis);
    }
}

void GameplaySession::Impl::gib_advance(GameWord actor, unsigned elapsed_units)
{
    for (unsigned piece = 0; piece < 4; ++piece)
    {
        const unsigned record = gib_records + piece * gib_size;
        auto& life = e(actor, record);
        if (piece)
            life -= static_cast<GameWord>(std::min<unsigned>(life, elapsed_units));
        if (life)
            gib_toss(actor, record, piece == 0);
    }
}

void GameplaySession::Impl::gib_toss(GameWord actor, unsigned record, bool head)
{
    auto value = [&](unsigned field, unsigned axis) -> GameWord& {
        return e(actor, record + field + 2 * axis);
    };
    if (!(value(gib_velocity, 0) | value(gib_velocity, 1) | value(gib_velocity, 2)))
        return;
    GamePoint from{}, to{};
    for (unsigned axis = 0; axis < 3; ++axis)
    {
        auto& velocity = value(gib_velocity, axis);
        velocity = gw(std::clamp<int>(gs(velocity), -2000 * 8, 2000 * 8) - (axis == 2 ? 40 * 8 : 0));
        auto& angle = value(gib_angles, axis);
        int turn = gs(angle) + gs(value(gib_spin, axis)) * 2 / 5;
        angle = gw((turn + 360 * 64) % (360 * 64));
        const auto origin = gs(value(gib_origin, axis));
        from[axis] = head ? gs(2 * (origin + (axis == 2 ? 24 * 8 : 0))) : origin;
        to[axis] = gs(from[axis] + gs(velocity) / (head ? 10 : 20));
    }
    const auto sweep = trace(from, to, !head);
    for (unsigned axis = 0; axis < 3; ++axis)
        value(gib_origin, axis) = gw(head ? game_asr(gs(sweep.result[axis] + 1), 1) - (axis == 2 ? 24 * 8 : 0)
                                          : sweep.result[axis]);
    if (sweep.hit)
    {
        std::int32_t dot = 0;
        for (unsigned axis = 0; axis < 3; ++axis)
            dot += gs(value(gib_velocity, axis)) * sweep.normal[axis];
        const auto projection = game_asr(dot, 14);
        const auto backoff = projection + game_asr(projection, 1);
        for (unsigned axis = 0; axis < 3; ++axis)
            value(gib_velocity, axis) = gw(value(gib_velocity, axis) - game_asr(backoff * sweep.normal[axis], 14));
        if (sweep.normal[2] >= 11469 && gs(value(gib_velocity, 2)) < 60 * 8)
        {
            if (head)
                field(actor, "FLAGS") |= 512;
            for (unsigned axis = 0; axis < 3; ++axis)
                value(gib_velocity, axis) = value(gib_spin, axis) = 0;
        }
    }
    if (head)
        for (unsigned axis = 0; axis < 3; ++axis)
        {
            field(actor, "ORIGIN", axis) = value(gib_origin, axis);
            field(actor, "VELOCITY", axis) = value(gib_velocity, axis);
            field(actor, "ANGLES", axis) = value(gib_angles, axis);
            field(actor, "AVELOCITY", axis) = value(gib_spin, axis);
        }
}
} // namespace quake_bsp_reference
