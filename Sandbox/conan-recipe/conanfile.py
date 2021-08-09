import json
import os
import re
from conans import ConanFile, CMake, tools

required_conan_version = ">=1.33.0"

class NmosCppConan(ConanFile):
    name = "nmos-cpp"
    description = "An NMOS C++ Implementation"
    license = "Apache-2.0"
    url = "https://github.com/conan-io/conan-center-index"
    homepage = "https://github.com/garethsb/nmos-cpp"
    topics = ("NMOS")

    settings = "os", "compiler", "build_type", "arch"
    # no "shared" option support
    # is anything else required to support "fPIC"?
    options = {"fPIC": [True, False]}
    default_options = {"fPIC": True}

    exports_sources = ["CMakeLists.txt"]
    # is this the right choice of generators?
    generators = "cmake", "cmake_find_package"
    _cmake = None

    def config_options(self):
        if self.settings.os == "Windows":
            del self.options.fPIC

    def requirements(self):
        # for now, consistent with project's conanfile.txt
        self.requires("boost/1.76.0")
        self.requires("openssl/1.1.1k")
        self.requires("cpprestsdk/2.10.18")
        self.requires("websocketpp/0.8.2")

    def source(self):
        tools.get(**self.conan_data["sources"][self.version],
            destination="nmos-cpp", strip_root=True)

    def _configure_cmake(self):
        if not self._cmake:
            self._cmake = CMake(self)
            self._cmake.configure()
        return self._cmake

    def build(self):
        cmake = self._configure_cmake()
        cmake.build()

    def package(self):
        self.copy("nmos-cpp/LICENSE", dst="licenses")
        cmake = self._configure_cmake()
        cmake.install()
        cmake_folder = os.path.join(self.package_folder, "lib", "cmake")
        self._create_components_file_from_cmake_target_file(os.path.join(cmake_folder, "nmos-cpp", "nmos-cpp-targets.cmake"))
        tools.rmdir(cmake_folder)

    # based on abseil recipe
    # see https://github.com/conan-io/conan-center-index/blob/master/recipes/abseil/all/conanfile.py
    def _create_components_file_from_cmake_target_file(self, target_file_path):
        components = {}

        target_file = open(target_file_path, "r")
        target_content = target_file.read()
        target_file.close()

        cmake_functions = re.findall(r"(?P<func>add_library|set_target_properties)[\n|\s]*\([\n|\s]*(?P<args>[^)]*)\)", target_content)
        for (cmake_function_name, cmake_function_args) in cmake_functions:
            cmake_function_args = re.split(r"[\s|\n]+", cmake_function_args, maxsplit=2)

            cmake_imported_target_name = cmake_function_args[0]
            cmake_target_nonamespace = cmake_imported_target_name.replace("nmos-cpp::", "")
            component_name = cmake_target_nonamespace.lower()
            # Conan component name cannot be the same as the package name
            if component_name == "nmos-cpp":
                component_name = "nmos-cpp-lib"
            lib_name = cmake_target_nonamespace
            # hmm, where is this info?
            # set_property(TARGET Bonjour PROPERTY OUTPUT_NAME dnssd)
            if lib_name == "Bonjour":
                lib_name = "dnssd"

            components.setdefault(component_name, {"cmake_target": cmake_target_nonamespace})

            if cmake_function_name == "add_library":
                cmake_imported_target_type = cmake_function_args[1]
                if cmake_imported_target_type in ["STATIC", "SHARED"]:
                    components[component_name]["libs"] = [lib_name]
            elif cmake_function_name == "set_target_properties":
                target_properties = re.findall(r"(?P<property>INTERFACE_[A-Z_]+)[\n|\s]+\"(?P<values>.+)\"", cmake_function_args[2])
                for target_property in target_properties:
                    property_type = target_property[0]
                    # '\', '$' and '"' are escaped; '$' especially is important here
                    # see https://github.com/conan-io/conan/blob/release/1.39/conans/client/generators/cmake_common.py#L43-L48
                    property_values = re.sub(r"\\(.)", r"\1", target_property[1]).split(";")
                    if property_type == "INTERFACE_LINK_LIBRARIES":
                        for dependency in property_values:
                            match_private = re.fullmatch(r"\$<LINK_ONLY:(.+)>", dependency)
                            if match_private:
                                dependency = match_private.group(1)
                            # nmos-cpp::, Boost::, cpprestsdk::, websocketpp:: and OpenSSL::
                            if "::" in dependency:
                                dependency = dependency.replace("nmos-cpp::", "")
                                # Conan component name cannot be the same as the package name
                                if dependency == "nmos-cpp":
                                    dependency = "nmos-cpp-lib"
                                components[component_name].setdefault("requires" if not match_private else "requires_private", []).append(dependency.lower())
                            else:
                                components[component_name].setdefault("system_libs", []).append(dependency)
                    elif property_type == "INTERFACE_COMPILE_DEFINITIONS":
                        for property_value in property_values:
                            components[component_name].setdefault("defines", []).append(property_value)
                    elif property_type == "INTERFACE_COMPILE_OPTIONS":
                        for property_value in property_values:
                            components[component_name].setdefault("cxxflags", []).append(property_value)
                    elif property_type == "INTERFACE_LINK_OPTIONS":
                        for property_value in property_values:
                            # workaround required because otherwise "/ignore:4099" gets converted to "\ignore:4099.obj"
                            # thankfully the MSVC linker accepts both '/' and '-' for the option specifier and Visual Studio
                            # handles link options appearing in Link/AdditionalDependencies rather than  Link/AdditionalOptions
                            # because the CMake generators put them in INTERFACE_LINK_LIBRARIES rather than INTERFACE_LINK_OPTIONS
                            # see https://github.com/conan-io/conan/pull/8812
                            # and https://docs.microsoft.com/en-us/cpp/build/reference/linking?view=msvc-160#command-line
                            property_value = re.sub(r"^/", r"-", property_value)
                            components[component_name].setdefault("linkflags", []).append(property_value)

        # Save components informations in json file
        with open(self._components_helper_filepath, "w") as json_file:
            json.dump(components, json_file, indent=4)

    @property
    def _components_helper_filepath(self):
        return os.path.join(self.package_folder, "lib", "components.json")

    def package_info(self):
        def _register_components():
            components_json_file = tools.load(self._components_helper_filepath)
            components = json.loads(components_json_file)
            for component_name, values in components.items():
                cmake_target = values["cmake_target"]
                self.cpp_info.components[component_name].names["cmake_find_package"] = cmake_target
                self.cpp_info.components[component_name].names["cmake_find_package_multi"] = cmake_target
                self.cpp_info.components[component_name].libs = values.get("libs", [])
                self.cpp_info.components[component_name].defines = values.get("defines", [])
                self.cpp_info.components[component_name].cxxflags = values.get("cxxflags", [])
                linkflags = values.get("linkflags", [])
                self.cpp_info.components[component_name].sharedlinkflags = linkflags
                self.cpp_info.components[component_name].exelinkflags = linkflags
                self.cpp_info.components[component_name].system_libs = values.get("system_libs", [])
                self.cpp_info.components[component_name].frameworks = values.get("frameworks", [])
                self.cpp_info.components[component_name].requires = values.get("requires", [])
                # hmm, how should private requirements be indicated? this results in a string format error...
                #self.cpp_info.components[component_name].requires.extend([(r, "private") for r in values.get("requires_private", [])])
                self.cpp_info.components[component_name].requires.extend(values.get("requires_private", []))
        _register_components()
