#include "gameplay_internal.hpp"

namespace quake_bsp_reference {

GameplaySession::Continuation::Continuation(Impl& engine)
:
engine_(engine)
{
    thread_ = std::thread([this] {
        bool result = false;
        std::exception_ptr error;
        engine_.checkpoint_hook = [this](std::string_view phase) { checkpoint(phase); };
        try
        {
            result = engine_.service_tick();
        }
        catch (...)
        {
            error = std::current_exception();
        }
        engine_.checkpoint_hook = {};
        {
            const std::lock_guard lock(mutex_);
            result_ = result;
            error_ = error;
            finished_ = true;
            paused_ = false;
        }
        condition_.notify_all();
    });
    std::unique_lock lock(mutex_);
    condition_.wait(lock, [this] { return paused_ || finished_; });
}

GameplaySession::Continuation::~Continuation()
{
    {
        const std::lock_guard lock(mutex_);
        cancelled_ = true;
    }
    condition_.notify_all();
    if (thread_.joinable())
        thread_.join();
}

void GameplaySession::Continuation::checkpoint(std::string_view phase)
{
    std::unique_lock lock(mutex_);
    phase_ = phase;
    paused_ = true;
    condition_.notify_all();
    condition_.wait(lock, [this] { return advance_ || cancelled_; });
    if (cancelled_)
        throw std::runtime_error("gameplay continuation cancelled");
    advance_ = false;
    paused_ = false;
}

std::string GameplaySession::Continuation::phase() const
{
    const std::lock_guard lock(mutex_);
    if (finished_)
    {
        if (error_)
            std::rethrow_exception(error_);
        return "done";
    }
    if (!paused_)
        throw std::runtime_error("gameplay service is executing");
    return phase_;
}

std::string GameplaySession::Continuation::resume()
{
    std::unique_lock lock(mutex_);
    if (finished_)
    {
        if (error_)
            std::rethrow_exception(error_);
        return "done";
    }
    if (!paused_)
        throw std::runtime_error("gameplay service is not suspended");
    paused_ = false;
    advance_ = true;
    condition_.notify_all();
    condition_.wait(lock, [this] { return paused_ || finished_; });
    if (error_)
        std::rethrow_exception(error_);
    return finished_ ? "done" : phase_;
}

bool GameplaySession::Continuation::result() const
{
    const std::lock_guard lock(mutex_);
    if (!finished_)
        throw std::runtime_error("gameplay service has not completed");
    if (error_)
        std::rethrow_exception(error_);
    return result_;
}

std::string GameplaySession::begin_service()
{
    if (continuation_ && continuation_->phase() != "done")
        throw std::runtime_error("gameplay service is already suspended");
    continuation_.reset();
    continuation_ = std::make_unique<Continuation>(*impl_);
    return continuation_->phase();
}

std::string GameplaySession::resume_service()
{
    if (!continuation_)
        throw std::runtime_error("gameplay service was not started");
    return continuation_->resume();
}

std::string GameplaySession::service_phase() const
{
    return continuation_ ? continuation_->phase() : std::string{};
}

} // namespace quake_bsp_reference
