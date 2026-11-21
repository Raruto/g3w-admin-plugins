@backend
Feature: Preparing and reloading the plugin configuration

  Background:
    Given an isolated reload directory

  Scenario: Preparation reports every phase
    When the configuration is prepared successfully
    Then migration, static collection and menu synchronization are reported in order

  Scenario: Preparation reports partial changes after a failed migration
    When migration fails during preparation
    Then the error warns that changes may already have been applied

  Scenario: Automatic reload requires a live consumer when enabled
    Given POSIX reload support
    When reload is requested with an unavailable or stale consumer
    Then no web reload signal is sent
    When the consumer heartbeat becomes current
    Then reload is requested for the current configuration

  Scenario: Automatic reload without a consumer signals only the web process
    Given POSIX reload support
    When reload is requested with the consumer disabled
    Then the web process is signalled without a consumer request

  Scenario: Only a fresh, ready, matching heartbeat confirms a reload
    When consumer heartbeats are checked against the requested configuration
    Then only the fresh, ready, matching heartbeat is accepted
    And invalid heartbeat data is logged and rejected

  Scenario: Reload is rejected during a CLI change
    Given POSIX reload support
    When reload is requested while a plugin change holds the lock
    Then the active change is reported and no signal is sent

  Scenario: Reload is rejected when the configuration changed
    Given POSIX reload support
    When reload is requested for an outdated configuration
    Then the configuration change is reported and no signal is sent

  Scenario: Consumer reloads when a different configuration is requested
    Given POSIX reload support
    When a ready consumer observes a request for the new configuration
    Then it reports its current state and signals itself to reload

  Scenario: A dead consumer worker is not reported ready
    Given POSIX reload support
    When a consumer worker has stopped
    Then the consumer heartbeat is not ready

  Scenario: A real consumer confirms only after its task completes and it restarts
    Given POSIX reload support
    When a running consumer task delays a configuration reload
    Then the consumer confirms only after the task finishes
