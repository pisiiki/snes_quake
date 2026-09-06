#pragma once

namespace quake_bsp_reference {

struct Vec3
{
    double x{};
    double y{};
    double z{};

    double operator[](int axis) const
    {
        if (axis == 0)
        {
            return x;
        }
        if (axis == 1)
        {
            return y;
        }
        return z;
    }
};

inline Vec3 operator+(const Vec3& left, const Vec3& right)
{
    return {left.x + right.x, left.y + right.y, left.z + right.z};
}

inline Vec3 operator-(const Vec3& left, const Vec3& right)
{
    return {left.x - right.x, left.y - right.y, left.z - right.z};
}

inline Vec3 operator*(const Vec3& value, double scale)
{
    return {value.x * scale, value.y * scale, value.z * scale};
}

inline double dot(const Vec3& left, const Vec3& right)
{
    return left.x * right.x + left.y * right.y + left.z * right.z;
}

inline Vec3 cross(const Vec3& left, const Vec3& right)
{
    return {
        left.y * right.z - left.z * right.y,
        left.z * right.x - left.x * right.z,
        left.x * right.y - left.y * right.x,
    };
}

inline double length_squared(const Vec3& value)
{
    return dot(value, value);
}

inline bool exactly_equal(const Vec3& left, const Vec3& right)
{
    return left.x == right.x && left.y == right.y && left.z == right.z;
}

} // namespace quake_bsp_reference
