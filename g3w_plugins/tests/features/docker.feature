@docker
Feature: Plugin manager in G3W Docker

  Background:
    Given a disposable G3W Docker test container

  Scenario: The manager preserves the published default configuration
    When the Docker settings are loaded with the default manager configuration
    Then the manager is enabled and the original portal configuration is retained

  Scenario: An explicitly enabled portal retains its settings
    When the Docker settings are loaded with an enabled portal
    Then portal and its settings remain configured

  Scenario: An absent manager preserves the original application settings
    When the published Docker settings are loaded without the manager
    Then portal remains configured without plugin manager state

  Scenario: The manager configures applications before portal settings
    When the manager disables portal in the Docker settings
    Then the manager remains while portal and its settings are omitted

  Scenario: Plugin commands prepare and disable a plugin
    Given the published G3W Docker settings with the manager and portal disabled in isolated state
    When panoramax is enabled through the management command
    Then the plugin is active and its URL, template and sitetrees are available
    When panoramax is disabled through the management command
    Then the plugin is disabled after restart
