

! eT - a coupled cluster program
! Copyright (C) 2016-2026 the authors of eT
!
! eT is free software: you can redistribute it and/or modify
! it under the terms of the GNU General Public License as published by
! the Free Software Foundation, either version 3 of the License, or
! (at your option) any later version.
!
! eT is distributed in the hope that it will be useful,
! but WITHOUT ANY WARRANTY; without even the implied warranty of
! MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
! GNU General Public License for more details.
!
! You should have received a copy of the GNU General Public License
! along with this program. If not, see <https://www.gnu.org/licenses/>.


module eT_class

   !!
   !! eT class
   !! Written by Eirik F. Kjønstad, May 2022
   !!

   use timings_class, only: timings

   implicit none

   type :: eT

      type(timings), allocatable, private :: timer

   contains

      procedure, public :: run

      procedure, public :: initialize
      procedure, public :: initialize_for_scripting
      procedure, public :: finalize
      procedure, public :: run_calculations

      procedure, private, nopass :: create_memory_manager

      procedure, private, nopass :: get_and_print_n_threads
      procedure, private, nopass :: set_global_print_levels_in_output_and_timing
      procedure, private, nopass :: print_compilation_info

      procedure, private :: print_timestamp
      procedure, private, nopass :: get_date_and_time

      procedure, private, nopass :: check_do_section_for_conflicting_keywords

      procedure, private, nopass :: cholesky_decompose_eris
      procedure, private         :: run_geometry_optimization
      procedure, private         :: run_harmonic_frequencies
      procedure, private         :: run_active_space_calculation
      procedure, public, nopass  :: run_reference_calculation
      procedure, private, nopass :: run_cc_calculation
      procedure, private, nopass :: run_ci_calculation
      procedure, private, nopass :: visualize_active_density

      procedure, private :: print_top_info_to_output_and_timing
      procedure, private :: print_bottom_info_to_output


   end type eT


   interface eT

      procedure :: new_eT

   end interface eT


contains


   function new_eT() result(this)
      !!
      !! Written by Eirik F. Kjønstad, May 2022
      !!
      implicit none

      type(eT) :: this

      this%timer = timings("Total time in eT", pl='minimal')

   end function new_eT


   subroutine run(this)
      !!
      !! Written by Sarai D. Folkestad, Eirik F. Kjønstad,
      !! Alexander C. Paul, and Rolf H. Myhre, 2018-2022
      !!
      use global_in

      implicit none

      class(eT), intent(inout) :: this

      input = input_tool()
      call input%read_input(file_name='eT.inp')
      call this%initialize()
      call this%run_calculations()
      call this%finalize()

   end subroutine run


   subroutine initialize(this)
      !!
      !! Written by Eirik F. Kjønstad, Mar 2024
      !!
      use global_in
      use global_out
      use timings_file_class,       only: timings_file
      use memory_manager_class,     only: mem
      use citation_printer_class,   only: eT_citations, citation_printer

#ifdef USE_LIBINT
      use libint_initialization, only: initialize_libint_c
#endif

      implicit none

      class(eT), intent(inout) :: this

      call this%timer%turn_on()
      output = output_file('eT.out')
      timing = timings_file('eT.timing.out')
      call output%open_()
      call timing%open_()
      call this%print_top_info_to_output_and_timing()
      call input%process_input()
      call this%set_global_print_levels_in_output_and_timing()

      eT_citations = citation_printer(input)
      mem = this%create_memory_manager(input)

#ifdef USE_LIBINT
      call initialize_libint_c() ! Safe to use Libint from now on
#endif

   end subroutine initialize


   function initialize_for_scripting(this) result(cfg)
      !!
      !! Creates input, runs initialize, and returns cfg for scripting.
      !!
      use global_in
      use et_config_class, only: et_config
      use input_tool_class, only: input_tool

      implicit none

      class(eT), intent(inout) :: this
      class(et_config), pointer :: cfg

      input = input_tool()
      call this%initialize()
      cfg => input%get_config()

   end function initialize_for_scripting


   subroutine finalize(this)
      !!
      !! Written by Eirik F. Kjønstad, Mar 2024
      !!
      use global_out
      use global_in
      use memory_manager_class, only: mem

#ifdef USE_LIBINT
      use libint_initialization, only: finalize_libint_c
#endif

      implicit none

      class(eT), intent(inout) :: this

      call mem%check_for_leak()
      call input%cleanup()

      call this%timer%turn_off()

      call output%check_for_warnings()
      call this%print_bottom_info_to_output()

#ifdef USE_LIBINT
      call finalize_libint_c() ! No longer safe to use Libint
#endif

      call timing%close_()

      call output%printf('m', 'eT terminated successfully!', fs='(/t3,a)')
      call output%close_()

   end subroutine finalize

   subroutine print_timestamp(this, print_label)
      !!
      !! Written by Eirik F. Kjønstad, May 2022
      !!
      use global_out, only: output

      implicit none

      class(eT), intent(in) :: this

      character(len=*), intent(in) :: print_label

      character(len=50) :: timestamp

      call this%get_date_and_time(timestamp)
      call output%printf('m', 'Calculation (a0):', chars=[print_label], fs='(/t3,a)', adv=.false.)
      call output%printf('m', " (a0)", chars=[timestamp], fs='(t1,a)')

   end subroutine print_timestamp


   subroutine get_and_print_n_threads()
      !!
      !! Written by Eirik F. Kjønstad, May 2022
      !!
      use omp_lib
      use global_out, only: output

      implicit none

      integer :: n_threads

      n_threads = 1

      !$    n_threads = omp_get_max_threads()

      if (n_threads .eq. 1) then

         call output%printf('m', 'Running on (i0) OMP thread', ints=[n_threads], fs='(/t3,a)')

      else

         call output%printf('m', 'Running on (i0) OMP threads', ints=[n_threads], fs='(/t3,a)')

      endif

   end subroutine get_and_print_n_threads


   function create_memory_manager(input) result(mem_manager)
      !!
      !! Written by Eirik F. Kjønstad, May 2022
      !!
      use parameters
      use memory_manager_class, only: memory_manager
      use input_tool_class, only: input_tool

      implicit none

      class(input_tool), intent(in) :: input

      character(len=200) :: mem_unit
      integer(i64)       :: mem_total

      type(memory_manager) :: mem_manager

      mem_total = 8
      mem_unit  = 'gb'

      call input%get_keyword('available', 'memory', mem_total)
      call input%get_keyword('unit',      'memory', mem_unit)

      mem_manager = memory_manager(total = mem_total, &
                                   units = mem_unit)

   end function create_memory_manager


   subroutine run_calculations(this)
      !!
      !! Written by Eirik F. Kjønstad, May 2022
      !!
      use global_out, only: output
      use global_in, only: input
      use density_environment_class, only: density_environment
      use hf_class, only: hf

      implicit none

      class(eT), intent(in) :: this
      class(hf), allocatable :: ref_wf

      type(density_environment), allocatable :: embedding


      logical :: requested_cholesky

      call check_do_section_for_conflicting_keywords()

      ! Cholesky decomposition of electron repulsion integrals (ERIs)
      requested_cholesky = input%is_keyword_present('cholesky eri', 'do')
      if (requested_cholesky) call cholesky_decompose_eris(input%is_keyword_present('diagonal test', 'solver cholesky'))

      if (input%is_keyword_present('geometry optimization', 'do')) then

         call this%run_geometry_optimization(ref_wf)

      elseif (input%is_keyword_present('harmonic frequencies','do')) then

         call this%run_harmonic_frequencies(ref_wf)

      elseif (input%requested_reference_calculation()) then

         call this%run_reference_calculation(ref_wf)

         if (input%requested_active_space_calculation()) then

            call this%run_active_space_calculation(ref_wf, embedding)

         end if

         if (input%requested_cc_calculation()) then

            call this%run_cc_calculation(ref_wf, embedding)

         else if (input%requested_ci_calculation()) then

            call this%run_ci_calculation(ref_wf, embedding)

         endif

         call ref_wf%cleanup()
         deallocate(ref_wf)

      else

         if (input%requested_cc_calculation()) &
            call output%error_msg('to run CC calculation reference wavefunction must be specified.')

         if (.not. requested_cholesky) &
            call output%error_msg('no method nor ERI Cholesky decomposition selected in input.')

      endif

   end subroutine run_calculations


   subroutine check_do_section_for_conflicting_keywords()
      !!
      !! Written by Leo Stoll, 2025
      !!
      !! Checks if the do section contains keywords for multiple engines.
      !! Note that the keywords 'restart' and 'cholesky eri' do not specify an engine.
      !!
      use global_out, only: output
      use global_in, only: input

      implicit none

      character(len=200), dimension(:), allocatable :: keywords
      character(len=200), dimension(:), allocatable :: keywords_masked
      logical, dimension(:), allocatable            :: mask
      character(len=:), allocatable                 :: keywords_string

      integer :: i

      call input%get_present_keywords('do', keywords)

      mask = [( trim(keywords(i)) /= 'restart' .and. trim(keywords(i)) /= 'cholesky eri', i=1, size(keywords) )]
      keywords_masked = pack(keywords, mask)

      if (size(keywords_masked) .gt. 1) then

         keywords_string = ""
         do i = 1, size(keywords_masked)

            if (i > 1) keywords_string = keywords_string // ","
            keywords_string = trim(keywords_string) // "'" // trim(keywords_masked(i)) // "'"

         end do

         call output%error_msg("Keywords for multiple types of calculations specified in the do section. &
                              &Only one of the specified keywords " // keywords_string // " can be included. &
                              &It is possible that these types of calculations are conflicting or that one &
                              &implies the other. Check 'https://etprogram.org/required_sections.html#do' for details")

         deallocate(keywords_string)

      end if

      deallocate(keywords)
      deallocate(keywords_masked)
      deallocate(mask)

   end subroutine check_do_section_for_conflicting_keywords


   subroutine run_geometry_optimization(this, ref_wf)
      !!
      !! Written by Eirik F. Kjønstad, 2022
      !!
      use hf_class, only: hf
      use ccs_class, only: ccs

      use reference_wavefunction_factory_class, only: reference_wavefunction_factory
      use cc_wavefunction_factory_class, only: cc_wavefunction_factory

      use geoopt_engine_class, only: geoopt_engine

      use global_in, only: input

      implicit none

      class(eT), intent(in) :: this

      class(hf), allocatable, intent(inout)              :: ref_wf
      class(reference_wavefunction_factory), allocatable :: ref_wf_factory

      class(geoopt_engine), allocatable :: engine

      class(ccs), allocatable                    :: cc_wf
      type(cc_wavefunction_factory), allocatable :: cc_wf_factory

      if (.not. input%requested_cc_calculation()) then

         ref_wf_factory = reference_wavefunction_factory()
         call ref_wf_factory%create(ref_wf)

         engine = geoopt_engine()
         call engine%run(ref_wf)

      else

         call this%run_reference_calculation(ref_wf)

         cc_wf_factory = cc_wavefunction_factory()
         call cc_wf_factory%create(ref_wf, cc_wf)

         engine = geoopt_engine()
         call engine%run(cc_wf, ref_wf)

         call cc_wf%cleanup()

      endif

      call ref_wf%cleanup()
      deallocate(ref_wf)

   end subroutine run_geometry_optimization


   subroutine run_harmonic_frequencies(this, ref_wf)
      !!
      !! Written by Eirik F. Kjønstad, 2022
      !!
      use hf_class, only: hf
      use ccs_class, only: ccs

      use reference_wavefunction_factory_class, only: reference_wavefunction_factory
      use cc_wavefunction_factory_class, only: cc_wavefunction_factory

      use harmonic_frequencies_engine_class, only: harmonic_frequencies_engine
      use geoopt_engine_class, only: geoopt_engine

      use global_in, only: input

      implicit none

      class(eT), intent(in) :: this

      class(hf), allocatable, intent(inout)              :: ref_wf
      class(reference_wavefunction_factory), allocatable :: ref_wf_factory

      class(harmonic_frequencies_engine), allocatable :: engine
      class(geoopt_engine), allocatable :: optimization_engine

      class(ccs), allocatable                    :: cc_wf
      type(cc_wavefunction_factory), allocatable :: cc_wf_factory

      if (.not. input%requested_cc_calculation()) then

         ref_wf_factory = reference_wavefunction_factory()
         call ref_wf_factory%create(ref_wf)

         if (input%is_keyword_present('run geometry optimization', 'harmonic frequencies')) then

            optimization_engine = geoopt_engine()
            call optimization_engine%run(ref_wf)

         endif

         engine = harmonic_frequencies_engine(ref_wf)
         call engine%initialize()
         call engine%run()

      else

         call this%run_reference_calculation(ref_wf)

         cc_wf_factory = cc_wavefunction_factory()
         call cc_wf_factory%create(ref_wf, cc_wf)

         if (input%is_keyword_present('run geometry optimization', 'harmonic frequencies')) then

            optimization_engine = geoopt_engine()
            call optimization_engine%run(cc_wf, ref_wf)

         endif

         engine = harmonic_frequencies_engine(ref_wf, cc_wf)
         call engine%initialize()
         call engine%run()

         call cc_wf%cleanup()

      endif

      call ref_wf%cleanup()
      deallocate(ref_wf)

   end subroutine run_harmonic_frequencies


   subroutine run_reference_calculation(ref_wf)
      !!
      !! Written by Sarai D. Folkestad and Eirik F. Kjønstad, Apr 2019
      !!
      use hf_class, only: hf
      use hf_engine_class, only: hf_engine
      use reference_wavefunction_factory_class, only: reference_wavefunction_factory
      use reference_engine_factory_class, only: reference_engine_factory

      implicit none

      class(hf), allocatable, intent(inout)              :: ref_wf
      class(reference_wavefunction_factory), allocatable :: ref_wf_factory

      class(hf_engine), allocatable  :: ref_engine
      type(reference_engine_factory) :: ref_engine_factory

      ref_wf_factory = reference_wavefunction_factory()

      call ref_wf_factory%create(ref_wf)

      call ref_engine_factory%create(ref_engine)

      call ref_engine%ignite(ref_wf)

   end subroutine run_reference_calculation

   subroutine run_cc_calculation(ref_wf, embedding)
      !!
      !! Written by Sarai D. Folkestad and Eirik F. Kjønstad, Apr 2019
      !!
      use hf_class, only: hf

      use ccs_class,                      only: ccs
      use cc_wavefunction_factory_class,  only: cc_wavefunction_factory

      use cc_engine_class,          only: cc_engine
      use cc_engine_factory_class,  only: cc_engine_factory

      use density_environment_class, only: density_environment

      implicit none

      class(hf), intent(in) :: ref_wf

      class(ccs), allocatable                    :: cc_wf
      type(cc_wavefunction_factory), allocatable :: cc_wf_factory

      class(cc_engine), allocatable        :: engine
      type(cc_engine_factory), allocatable :: engine_factory

      type(density_environment), allocatable :: embedding

      cc_wf_factory = cc_wavefunction_factory()
      if (allocated(embedding)) then
         call cc_wf_factory%create(ref_wf, cc_wf, embedding)
      else
         call cc_wf_factory%create(ref_wf, cc_wf)
      endif

      allocate(cc_engine_factory::engine_factory)
      call engine_factory%create(engine)

      call engine%ignite(cc_wf)

      call cc_wf%cleanup()

   end subroutine run_cc_calculation

   subroutine run_active_space_calculation(this, ref_wf, embedding)
      !!
      !! Written by Sarai D. Folkestad and Eirik F. Kjønstad, Apr 2019
      !!
      use hf_class, only: hf
      use density_environment_class, only: density_environment
      use global_in, only: input

      implicit none

      class(eT), intent(in) :: this
      class(hf), intent(inout) :: ref_wf
      type(density_environment), allocatable :: embedding

      call ref_wf%prepare_for_post_HF_method(embedding)

      if (input%is_keyword_present('plot hf active density',  'visualization')) &
         call this%visualize_active_density(ref_wf)

   end subroutine run_active_space_calculation

   subroutine visualize_active_density(ref_wf)
      !!
      !! Written by Ida-Marie Høyvik, Oct 2019
      !!
      use parameters
      use memory_manager_class, only: mem
      use visualization_class, only: visualization
      use hf_class, only: hf

      implicit none

      class(hf), intent(inout) :: ref_wf
      real(dp), dimension(:,:), allocatable :: density
      character(len=:), allocatable :: density_file_tag

      class(visualization), allocatable :: visualizer

      visualizer = visualization(ref_wf%ao)
      call visualizer%initialize(ref_wf%ao)

      call mem%alloc(density, ref_wf%ao%n, ref_wf%ao%n)
      call dgemm('N', 'T',                    &
                  ref_wf%ao%n,                &
                  ref_wf%ao%n,                &
                  ref_wf%n_o,                 &
                  two,                        &
                  ref_wf%orbital_coefficients,&
                  ref_wf%ao%n,                &
                  ref_wf%orbital_coefficients,&
                  ref_wf%ao%n,                &
                  zero,                       &
                  density,                    &
                  ref_wf%ao%n)

      allocate(density_file_tag, source="active_" // trim(ref_wf%name_) // '_density')
      call visualizer%plot_density(ref_wf%ao, density, density_file_tag)

      call mem%dealloc(density)
      call visualizer%cleanup()

   end subroutine visualize_active_density

   subroutine run_ci_calculation(ref_wf, embedding)
      !!
      !! Written by Enrico Ronca, 2020
      !!
      use hf_class, only: hf

      use density_environment_class, only: density_environment
      use fci_class,                      only: fci
      use ci_wavefunction_factory_class,  only: ci_wavefunction_factory

      use ci_engine_class, only: ci_engine

      implicit none

      class(hf), intent(in) :: ref_wf

      class(fci), allocatable                     :: ci_wf
      type(ci_wavefunction_factory), allocatable  :: ci_wf_factory

      class(ci_engine), allocatable :: engine

      type(density_environment), allocatable :: embedding

      ci_wf_factory = ci_wavefunction_factory()
      call ci_wf_factory%create(ref_wf, ci_wf, embedding)

      engine = ci_engine()

      call engine%ignite(ci_wf)

      call ci_wf%cleanup()

   end subroutine run_ci_calculation

   subroutine cholesky_decompose_eris(diagonal_test)
      !!
      !! Written by Eirik F. Kjønstad and Sarai D. Folkestad, Apr 2019 and Dec 2019
      !!
      !! Performs Cholesky decomposition of the electron repulsion integral matrix.
      !!
      use eri_cd_class,  only: eri_cd
      use ao_tool_class, only: ao_tool
      use ao_eri_getter_class, only: ao_eri_getter

      implicit none

      logical, intent(in) :: diagonal_test

      type(eri_cd), allocatable  :: eri_cholesky_solver
      class(ao_tool), allocatable :: ao
      type(ao_eri_getter) :: eri_getter

      ao = ao_tool()
      call ao%initialize()

      eri_getter = ao_eri_getter(ao)
      eri_cholesky_solver = eri_cd(ao, eri_getter)

      call eri_cholesky_solver%run(ao)

      if (diagonal_test) then

         ! Determine the largest deviation in the ERI matrix
         call eri_cholesky_solver%diagonal_test(ao)

      end if

      call eri_cholesky_solver%cleanup()

   end subroutine cholesky_decompose_eris

   subroutine set_global_print_levels_in_output_and_timing()
      !!
      !! Written by Rolf H. Myhre, Oct. 2019
      !!
      use global_out, only: output, timing
      use global_in,  only: input

      implicit none

      character(len=200) :: print_level

      print_level = 'normal'
      call input%get_keyword('output print level', 'print', print_level)

      ! This is the only place this routine is allowed to be called
      call output%set_global_print_level(print_level)

      ! Repeat for timing file
      print_level = 'normal'
      call input%get_keyword('timing print level', 'print', print_level)

      ! This is the only place this routine is allowed to be called
      call timing%set_global_print_level(print_level)

   end subroutine set_global_print_levels_in_output_and_timing

   subroutine print_top_info_to_output_and_timing(this)
      !!
      !! Written by Eirik F. Kjønstad, 2019
      !!
      use parameters
      use global_out, only: output, timing

      implicit none

      class(eT), intent(in) :: this

      call output%printf('m', 'eT (i0).(i0) - an electronic structure program ', &
                      ints=[major_version, minor_version], fs='(///t22,a)')

      call output%print_separator('m',72,'-', fs='(/t3,a)')

      call output%printf('m', 'Author list in alphabetical order:', fs='(t4,a)')

      call output%print_separator('m',72,'-', fs='(t3,a)')

      call output%printf('m', 'R. Alessandro, '          // &
                              'J. H. Andersen, '         // &
                              'S. Angelico, '            // &
                              'A. Balbi, '               // &
                              'A. Barlini, '             // &
                              'A. Bianchi, '             // &
                              'C. Cappelli, '            // &
                              'M. Castagnola, '          // &
                              'S. Coriani, '             // &
                              'S. D. Folkestad, '        // &
                              'Y. El Moutaoukal, '       // &
                              'T. Giovannini, '          // &
                              'L. Goletto, '             // &
                              'E. D. Hansen, '           // &
                              'T. S. Haugland, '         // &
                              'D. Hollas, '              // &
                              'A. Hutcheson, '           // &
                              'I-M. Høyvik, '            // &
                              'E. F. Kjønstad, '         // &
                              'H. Koch, '                // &
                              'M. T. Lexander, '         // &
                              'D. Lipovec, '             // &
                              'G. Marrazzini, '          // &
                              'T. Moitra, '              // &
                              'R. H. Myhre, '            // &
                              'Y. Os, '                  // &
                              'A. C. Paul, '             // &
                              'R. Paul, '                // &
                              'J. Pedersen, '            // &
                              'M. Rinaldi, '             // &
                              'R. R. Riso, '             // &
                              'S. Roet, '                // &
                              'E. Ronca, '               // &
                              'F. Rossi, '               // &
                              'B. S. Sannes, '           // &
                              'M. Scavino, '             // &
                              'A. K. Schnack-Petersen, ' // &
                              'A. S. Skeidsvoll, '       // &
                              'L. Stoll, '               // &
                              'G. Thiam, '               // &
                              'J. H. M. Trabski, '       // &
                              'Å. H. Tveten',               &
                              ffs='(t4,a)', fs='(t4,a)', ll=68)

      call output%print_separator('m',72,'-', fs='(t3,a)')

      call output%printf('m', 'J. Chem. Phys. 152, 184103 (2020); https://doi.org/10.1063/5.0004713', &
                      fs='(t4,a)')

      call output%printf('m', "This is eT (i0).(i0).(i0) (a0)", &
                         ints=[major_version, minor_version, patch_version], &
                         chars = [version_name], fs='(//t4,a)')

      call this%print_compilation_info(output)
      call this%print_compilation_info(timing)

      call timing%print_banner()

      call this%print_timestamp(print_label = 'start')

      call this%get_and_print_n_threads()

   end subroutine print_top_info_to_output_and_timing


   subroutine print_bottom_info_to_output(this)
      !!
      !! Written by Eirik F. Kjønstad, May 2022
      !!
      use memory_manager_class, only: mem
      use citation_printer_class, only: eT_citations
      use global_out, only: output

      implicit none

      class(eT), intent(in) :: this

      call mem%print_max_used()

      call this%timer%print_to_file(output, string="in eT")

      call this%print_timestamp(print_label = 'end')

      call eT_citations%print_(output)

   end subroutine print_bottom_info_to_output


   subroutine get_date_and_time(string)
      !!
      !! Written by Rolf H. Myhre, Nov, 2020
      !!
      !! Returns a formatted string with date, time and UTC offset
      !!
      !! Format: yyyy-mm-dd hh:mm:ss UTC xhh:mm
      !!
      implicit none

      character(len=*), intent(out) :: string
      character(len=20) :: date, time, zone

      call date_and_time(date=date, time=time, zone=zone)

      string = ""
      write(string, "(a,a,a,a,a,a)") date(1:4), "-", date(5:6), "-", date(7:8), " "
      write(string(12:), "(a,a,a,a,a)") time(1:2), ":", time(3:4), ":", time(5:6)
      write(string(20:), "(a,a,a,a)") " UTC ", zone(1:3), ":", zone(4:5)

   end subroutine get_date_and_time


   subroutine print_compilation_info(file_)
      !!
      !! Written by Rolf H. Myhre, Nov, 2020
      !!
      !! Retrieves compilation information from the
      !! get_compilation_info library generated by CMake
      !! and prints to output
      !!
      use output_file_class, only: output_file

      implicit none

      class(output_file), intent(inout) :: file_

      character(len=200) :: string

      call file_%print_separator('n',61,'-', fs='(t3,a)')

      call get_configuration_time(string)
      call file_%printf("m", "Configuration date:  (a0)", chars =[string])

      call get_git_branch(string)
      if(len_trim(string) .gt. 0) then
         call file_%printf("m", "Git branch:          (a0)", chars =[string])

         call get_git_hash(string)
         call file_%printf("m", "Git hash:            (a0)", chars =[string])
      endif

      call get_fortran_compiler(string)
      call file_%printf("m", "Fortran compiler:    (a0)", chars =[string])

      call get_c_compiler(string)
      call file_%printf("m", "C compiler:          (a0)", chars =[string])

      call get_cxx_compiler(string)
      call file_%printf("m", "C++ compiler:        (a0)", chars =[string])

      call get_lapack_type(string)
      call file_%printf("m", "LAPACK type:         (a0)", chars =[string])

      call get_blas_type(string)
      call file_%printf("m", "BLAS type:           (a0)", chars =[string])

      call get_oei_type(string)
      call file_%printf("m", "OEI type:            (a0)", chars =[string])

      call get_eri_type(string)
      call file_%printf("m", "ERI type:            (a0)", chars =[string])

      call get_int64(string)
      call file_%printf("m", "64-bit integers:     (a0)", chars =[string])

      call get_omp(string)
      call file_%printf("m", "OpenMP:              (a0)", chars =[string])

      call get_pcm(string)
      call file_%printf("m", "PCM:                 (a0)", chars =[string])

      call get_forced_batching(string)
      call file_%printf("m", "Forced batching:     (a0)", chars =[string])

      call get_runtime_check(string)
      call file_%printf("m", "Runtime checks:      (a0)", chars =[string])

      call get_initialize_nan_check(string)
      call file_%printf("m", "Initializing to NAN: (a0)", chars =[string])

      call file_%print_separator("m",61,"-", fs="(t3,a)")

   end subroutine print_compilation_info


end module eT_class
