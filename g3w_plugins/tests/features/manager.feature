@backend
Feature: Managing plugin configuration

  Background:
    Given an isolated plugin configuration

  Scenario: Docker supplies a default plugin directory
    When the manager runs in Docker without a configured directory
    Then the Docker plugin directory is used

  Scenario: Configuring an existing manager does not duplicate it
    When the manager configures an app list containing itself
    Then the manager appears only once

  Scenario: Enabling and disabling a plugin preserves unmanaged apps
    When panoramax is enabled and then disabled
    Then unmanaged applications remain configured

  Scenario: Preparation failure preserves the previous state
    When preparation of panoramax fails before publication
    Then the previous state remains and the candidate is removed

  Scenario: Updating a plugin preserves other versions and rejects invalid upgrades
    Given panoramax and portal are installed
    When panoramax is updated to version 1.1
    Then portal remains pinned and failed preparation preserves the state
    And non-newer and prerelease versions are rejected
    And successful preparation publishes a new site

  Scenario: Updating a disabled plugin does not enable it
    When an update is requested for disabled panoramax
    Then the update is rejected before installation

  Scenario: Bundled modules do not install packages
    Given an external portal installation
    When filemanager is disabled and enabled
    Then the external installation remains unchanged and pip is not called
    And updating filemanager as a package is rejected

  Scenario: An available bundled module can be enabled without external packages
    When qplotly is available but qtimeseries is missing
    Then qplotly is enabled and the missing module is rejected

  Scenario: Editing cannot be disabled while qes is installed
    When editing is disabled with qes installed
    Then the dependency error is reported without changing state

  Scenario: Failed bundled module preparation preserves configuration
    When disabling filemanager fails during preparation
    Then the bundled configuration remains unchanged

  Scenario: Bundled modules are excluded from external package installation
    When panoramax is installed alongside filemanager
    Then pip is not asked to install filemanager

  Scenario: Untrusted package names and invalid saved state are rejected
    When untrusted plugin names and an invalid site path are supplied
    Then they are rejected without installing packages

  Scenario: Injected update versions are rejected before pip
    Given panoramax and portal are installed
    When requested or installed versions contain injected text
    Then both versions are rejected before installation

  Scenario: Preparation keeps the lock after its parent is terminated
    When a preparation parent is terminated while its command is running
    Then the lock is held until the command exits and no state is published
