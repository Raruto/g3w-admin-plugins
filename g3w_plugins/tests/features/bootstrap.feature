@backend
Feature: Automatic integration with G3W settings

  Scenario: The manager applies saved state before plugin-dependent settings
    Given G3W settings with "absent" manager registration
    And portal is disabled in "published" state
    When the G3W settings are imported with the startup hook
    Then portal and its settings are disabled

  Scenario: Preparation uses the candidate instead of published state
    Given G3W settings with "absent" manager registration
    And portal is disabled in "candidate" state
    When the G3W settings are imported with the startup hook
    Then portal and its settings are disabled

  Scenario: An annotated application list is supported
    Given G3W settings with "annotated" manager registration
    And portal is disabled in "published" state
    When the G3W settings are imported with the startup hook
    Then portal and its settings are disabled

  Scenario: Explicit configuration remains supported
    Given G3W settings with "manual" manager registration
    And portal is disabled in "published" state
    When the G3W settings are imported with the startup hook
    Then portal and its settings are disabled

  Scenario: An existing explicit call does not duplicate the plugin path
    Given G3W settings with "manual-with-marker" manager registration
    And portal is enabled in an isolated installation
    When the G3W settings are imported with the startup hook
    Then the plugin installation is on the Python path once

  Scenario: Installation activates the manager without changing the configured plugins
    Given G3W settings with "absent" manager registration
    When the G3W settings are imported with the startup hook
    Then portal and its settings are enabled with the manager

  Scenario: An unrelated project with the same settings module name is unchanged
    Given G3W settings with "unrelated" manager registration
    And portal is disabled in "published" state
    When the G3W settings are imported with the startup hook
    Then portal and its settings are enabled without the manager

  Scenario: An existing late registration does not duplicate the manager
    Given G3W settings with "late" manager registration
    When the G3W settings are imported with the startup hook
    Then the manager appears once in the imported settings

  Scenario: Unsupported settings fail explicitly
    Given G3W settings with "conditional" manager registration
    When the G3W settings are imported with the startup hook
    Then startup reports that the manager could not configure G3W

  Scenario: Settings cannot silently overwrite a managed decision
    Given G3W settings with "overwrite" manager registration
    And portal is disabled in "published" state
    When the G3W settings are imported with the startup hook
    Then startup reports that the portal state was overwritten
