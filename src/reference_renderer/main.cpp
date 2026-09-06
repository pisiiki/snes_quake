#include <exception>
#include <iostream>

#include "application.hpp"

int main(int argc, char** argv)
{
    try
    {
        return quake_bsp_reference::run_application(argc, argv);
    }
    catch (const std::exception& error)
    {
        std::cerr << "error: " << error.what() << '\n';
        return 1;
    }
}
