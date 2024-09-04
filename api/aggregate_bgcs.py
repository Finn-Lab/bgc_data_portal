
class BgcAggregator:
    """Find union/interection of BGCs from different detectors"""
    @staticmethod
    def aggregate_results(aggregated_bgcs):
        """Create a list of aggregagted regions given results from intersection and union functions"""
        aggregated_results = []
        for group,aggregated_bgcs in aggregated_bgcs:
            group.mgybs = list({mgyb for bgc in aggregated_bgcs for mgyb in bgc.mgybs})
            group.bgc_detector_names = list({detector for bgc in aggregated_bgcs for detector in bgc.bgc_detector_names})
            group.bgc_class_names = list({_class for bgc in aggregated_bgcs for _class in bgc.bgc_class_names})
            aggregated_results.append(group)
        return aggregated_results

    @staticmethod
    def single(individual_bgcs,n_detectors=2):
        return individual_bgcs

    @staticmethod
    def union(individual_bgcs,n_detectors=2):
        grouped_by_contig = {}
        
        # Step 1: Group by mgyc
        for bgc in individual_bgcs:
            grouped_by_contig.setdefault(bgc.mgyc,[]).append(bgc)

        output_bgcs = []

        # Step 2: Process each group for overlapping regions
        for bgcs in grouped_by_contig.values():
            
            if len(bgcs)<n_detectors:
                continue

            # Sort bgcs by start_position to make it easier to detect overlaps
            bgcs.sort(key=lambda s: s.start_position)


            current_group = bgcs[0]
            aggregated_bgcs = [current_group]

            for i in range(1, len(bgcs)):
                bgc = bgcs[i]
                
                # Check if current bgc overlaps with the current group
                if bgc.start_position <= current_group.end_position:

                    current_group.end_position = max(current_group.end_position, bgc.end_position)
                    aggregated_bgcs.append(bgc)

                elif len(aggregated_bgcs)>=n_detectors:
                    
                    # If not overlapping, save the current group and start a new one
                    output_bgcs.append((current_group,aggregated_bgcs))
                    # Start a new group
                    current_group = bgc
                    aggregated_bgcs = [current_group]

            # Don't forget to add the last group
            if len(aggregated_bgcs)>=n_detectors:
                output_bgcs.append((current_group,aggregated_bgcs))

        return BgcAggregator.aggregate_results(output_bgcs)
    
    @staticmethod
    def intersection(individual_bgcs,n_detectors=2):
        grouped_by_contig = {}
        # Step 1: Group by mgyc
        for bgc in individual_bgcs:
            grouped_by_contig.setdefault(bgc.mgyc,[]).append(bgc)

        output_bgcs = []
        # Step 2: Process each group for overlapping regions with all specified detector names
        for bgcs in grouped_by_contig.values():

            if len(bgcs)<n_detectors:
                continue
            # Sort bgcs by start_position to make it easier to detect overlaps
            bgcs.sort(key=lambda s: s.start_position)

            current_group = bgcs[0]
            aggregated_bgcs = [current_group]

            for i in range(1, len(bgcs)):
                bgc = bgcs[i]   
                # Check if the current bgc overlaps with the current group and has all detector names
                if bgc.start_position <= current_group.end_position:
                    
                    # Update the current group's end_position to the intersection
                    current_group.end_position = min(current_group.end_position, bgc.end_position)
                    current_group.start_position = max(current_group.start_position, bgc.start_position)
                    # Aggregate the values
                    aggregated_bgcs.append(bgc)

                elif len(aggregated_bgcs)>=n_detectors:
                    # If not overlapping, start a new group, or if it doesn't match all detector names, skip
                    output_bgcs.append((current_group,aggregated_bgcs))

                    current_group = bgc
                    aggregated_bgcs = [current_group]

            # Don't forget to add the last group if it meets the criteria
            if len(aggregated_bgcs)>=n_detectors:
                output_bgcs.append((current_group,aggregated_bgcs))

        return BgcAggregator.aggregate_results(output_bgcs) 